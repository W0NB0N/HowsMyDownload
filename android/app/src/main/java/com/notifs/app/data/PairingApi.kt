package com.notifs.app.data

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Blocking HTTP calls to the pairing API. Call from Dispatchers.IO.
 *
 * The phone authenticates with the device secret the server issues at claim time; it never
 * sees the extension's secret, and the server only stores a hash of either.
 */
object PairingApi {

    data class ClaimResult(val pairingId: String, val pcName: String, val deviceSecret: String)

    class ApiException(val code: Int, message: String) : IOException(message)

    private val JSON = "application/json; charset=utf-8".toMediaType()

    private val client = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .writeTimeout(5, TimeUnit.SECONDS)
        .build()

    // Commands run inside a BroadcastReceiver's goAsync() window (~10s): cap the whole call
    private val commandClient = client.newBuilder()
        .callTimeout(8, TimeUnit.SECONDS)
        .build()

    /** HTTP status of a command request, plus how long ago the server last heard from the PC. */
    data class CommandResponse(val code: Int, val pcLastSeenSec: Int?)

    private fun endpoint(serverUrl: String, path: String) = serverUrl.trim().trimEnd('/') + path

    /**
     * Asks the PC to pause/resume/restart a download. The server queues it for the extension;
     * 202 means queued, not executed. Throws IOException on network failure.
     */
    fun sendCommand(
        serverUrl: String,
        pairingId: String,
        deviceSecret: String,
        downloadId: String,
        action: String
    ): CommandResponse {
        val body = JSONObject()
            .put("download_id", downloadId)
            .put("action", action)
            .toString()
            .toRequestBody(JSON)
        val request = Request.Builder()
            .url(endpoint(serverUrl, "/v1/pairings/$pairingId/commands"))
            .header("Authorization", "Bearer $deviceSecret")
            .post(body)
            .build()
        commandClient.newCall(request).execute().use { response ->
            val lastSeen = if (response.isSuccessful) {
                runCatching {
                    val json = JSONObject(response.body?.string().orEmpty())
                    if (json.isNull("pc_last_seen_sec")) null else json.getInt("pc_last_seen_sec")
                }.getOrNull()
            } else {
                null
            }
            return CommandResponse(response.code, lastSeen)
        }
    }

    /** Claims a pairing code. Throws ApiException (HTTP error) or IOException (network). */
    fun claim(serverUrl: String, code: String, fcmToken: String): ClaimResult {
        val body = JSONObject().put("fcm_token", fcmToken).toString().toRequestBody(JSON)
        val request = Request.Builder()
            .url(endpoint(serverUrl, "/v1/pairings/${code.trim().uppercase()}/claim"))
            .post(body)
            .build()

        client.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw ApiException(response.code, "Claim failed (${response.code})")
            }
            val json = JSONObject(text)
            val deviceSecret = json.optString("device_secret", "")
            if (deviceSecret.isBlank()) {
                // Server predates device credentials: refuse rather than pair half-way
                throw ApiException(response.code, "Server did not issue a device secret; update the server")
            }
            return ClaimResult(
                pairingId = json.getString("pairing_id"),
                pcName = json.optString("pc_name", "Desktop-PC"),
                deviceSecret = deviceSecret,
            )
        }
    }

    /** Registers a rotated FCM token. Returns the HTTP status code. */
    fun refreshToken(serverUrl: String, pairingId: String, deviceSecret: String, fcmToken: String): Int {
        val body = JSONObject().put("fcm_token", fcmToken).toString().toRequestBody(JSON)
        val request = Request.Builder()
            .url(endpoint(serverUrl, "/v1/pairings/$pairingId/token"))
            .header("Authorization", "Bearer $deviceSecret")
            .post(body)
            .build()
        return client.newCall(request).execute().use { it.code }
    }

    /** Deletes the pairing server-side. Returns the HTTP status code. */
    fun unpair(serverUrl: String, pairingId: String, deviceSecret: String): Int {
        val request = Request.Builder()
            .url(endpoint(serverUrl, "/v1/pairings/$pairingId"))
            .header("Authorization", "Bearer $deviceSecret")
            .delete()
            .build()
        return client.newCall(request).execute().use { it.code }
    }
}
