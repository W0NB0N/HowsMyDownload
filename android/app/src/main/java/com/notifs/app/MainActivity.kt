package com.notifs.app

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.google.firebase.messaging.FirebaseMessaging
import com.notifs.app.data.AppDownloadItem
import com.notifs.app.data.DownloadRepository
import com.notifs.app.data.PairingDataStore
import com.notifs.app.data.PairingInfo
import com.notifs.app.service.NotifFcmService
import com.notifs.app.service.NotificationHelper
import com.notifs.app.ui.QrScannerScreen
import com.notifs.app.ui.theme.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardCapitalization
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class MainActivity : ComponentActivity() {

    private lateinit var notificationHelper: NotificationHelper
    private lateinit var dataStore: PairingDataStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        notificationHelper = NotificationHelper(this)
        dataStore = PairingDataStore(this)

        setContent {
            DownloadNotifsTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = BgCanvas
                ) {
                    var showScanner by remember { mutableStateOf(false) }
                    var fcmToken by remember { mutableStateOf<String?>(null) }

                    // Fetch FCM token
                    LaunchedEffect(Unit) {
                        FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
                            if (task.isSuccessful) {
                                val token = task.result
                                fcmToken = token
                            }
                        }
                    }

                    if (showScanner) {
                        QrScannerScreen(
                            dataStore = dataStore,
                            fcmToken = fcmToken,
                            onDismiss = { showScanner = false },
                            onPairSuccess = { showScanner = false }
                        )
                    } else {
                        HomeScreen(
                            notificationHelper = notificationHelper,
                            dataStore = dataStore,
                            onOpenScanner = { showScanner = true }
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun HomeScreen(
    notificationHelper: NotificationHelper,
    dataStore: PairingDataStore,
    onOpenScanner: () -> Unit
) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    var fcmToken by remember { mutableStateOf<String?>("Fetching token...") }
    val pairingInfo by dataStore.pairingInfoFlow.collectAsState(initial = PairingInfo(null, null, null, false))
    val activeDownloads by DownloadRepository.downloadsFlow.collectAsState()

    var hasNotifPermission by remember {
        mutableStateOf(
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                ContextCompat.checkSelfPermission(
                    context,
                    Manifest.permission.POST_NOTIFICATIONS
                ) == PackageManager.PERMISSION_GRANTED
            } else {
                true
            }
        )
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        hasNotifPermission = isGranted
    }

    // Fetch live FCM token on launch
    LaunchedEffect(Unit) {
        FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
            if (task.isSuccessful) {
                val token = task.result
                fcmToken = token
                coroutineScope.launch {
                    dataStore.saveFcmToken(token)
                }
            } else {
                fcmToken = "Failed to retrieve FCM token: ${task.exception?.message}"
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // Header
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 8.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = "$ ",
                        color = PurpleLight,
                        fontSize = 18.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace
                    )
                    Text(
                        text = "notifs",
                        color = TextWhite,
                        fontSize = 18.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace
                    )
                    Text(
                        text = " // android",
                        color = TextMuted,
                        fontSize = 14.sp,
                        fontFamily = FontFamily.Monospace
                    )
                }
                Text(
                    text = "v0.1.0 · phase 6 pairing active",
                    color = TextMuted,
                    fontSize = 12.sp,
                    fontFamily = FontFamily.Monospace
                )
            }

            // Status Badge
            Surface(
                shape = RoundedCornerShape(4.dp),
                color = if (hasNotifPermission) GreenDim else BgElevated,
                border = BorderStroke(1.dp, if (hasNotifPermission) GreenNeon else BorderSubtle)
            ) {
                Text(
                    text = if (hasNotifPermission) "ONLINE" else "PERM REQ",
                    color = if (hasNotifPermission) GreenNeon else StatePaused,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold,
                    fontFamily = FontFamily.Monospace,
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)
                )
            }
        }

        // Permission Card (if needed)
        if (!hasNotifPermission && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            Card(
                colors = CardDefaults.cardColors(containerColor = BgCard),
                border = BorderStroke(1.dp, StatePaused),
                shape = RoundedCornerShape(6.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        text = "--permission [ POST_NOTIFICATIONS ]",
                        color = StatePaused,
                        fontWeight = FontWeight.Bold,
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace
                    )
                    Text(
                        text = "Notifications are required to show real-time lock-screen download progress bars.",
                        color = TextDim,
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace
                    )
                    Button(
                        onClick = { permissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS) },
                        colors = ButtonDefaults.buttonColors(containerColor = PurpleBrand),
                        shape = RoundedCornerShape(4.dp),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("Grant Permission", fontFamily = FontFamily.Monospace, fontSize = 12.sp)
                    }
                }
            }
        }

        // Pairing Status Card
        Card(
            colors = CardDefaults.cardColors(containerColor = BgCard),
            border = BorderStroke(1.dp, if (pairingInfo.isPaired) GreenNeon else BorderSubtle),
            shape = RoundedCornerShape(6.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "--pairing [ pc_relay ]",
                        color = PurpleLight,
                        fontWeight = FontWeight.Bold,
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace
                    )
                    Surface(
                        shape = RoundedCornerShape(3.dp),
                        color = if (pairingInfo.isPaired) GreenDim else BgElevated,
                        border = BorderStroke(1.dp, if (pairingInfo.isPaired) GreenNeon else BorderSubtle)
                    ) {
                        Text(
                            text = if (pairingInfo.isPaired) "PAIRED" else "UNPAIRED",
                            color = if (pairingInfo.isPaired) GreenNeon else TextMuted,
                            fontSize = 10.sp,
                            fontWeight = FontWeight.Bold,
                            fontFamily = FontFamily.Monospace,
                            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                        )
                    }
                }

                if (pairingInfo.isPaired) {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(
                            text = "PC: ${pairingInfo.pcName ?: "Desktop-PC"}",
                            color = TextWhite,
                            fontSize = 12.sp,
                            fontFamily = FontFamily.Monospace,
                            fontWeight = FontWeight.SemiBold
                        )
                        Text(
                            text = "Server: ${pairingInfo.serverUrl ?: "http://localhost:8000"}",
                            color = TextDim,
                            fontSize = 11.sp,
                            fontFamily = FontFamily.Monospace
                        )
                    }

                    Button(
                        onClick = {
                            coroutineScope.launch {
                                val sUrl = pairingInfo.serverUrl
                                val pId = pairingInfo.pairingId
                                withContext(Dispatchers.IO) {
                                    if (!sUrl.isNullOrBlank() && !pId.isNullOrBlank()) {
                                        try {
                                            val client = OkHttpClient.Builder()
                                                .connectTimeout(3, TimeUnit.SECONDS)
                                                .build()
                                            val req = Request.Builder()
                                                .url("${sUrl.trimEnd('/')}/v1/pairings/$pId")
                                                .delete()
                                                .build()
                                            client.newCall(req).execute()
                                        } catch (_: Exception) {}
                                    }
                                }
                                dataStore.clearPairing()
                                NotifFcmService.resetState()
                                notificationHelper.cancelAll()
                                DownloadRepository.clear()
                                Toast.makeText(context, "Unpaired", Toast.LENGTH_SHORT).show()
                            }
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = BgElevated),
                        border = BorderStroke(1.dp, StateFailed),
                        shape = RoundedCornerShape(4.dp),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(
                            text = "> unpair pc",
                            color = StateFailed,
                            fontFamily = FontFamily.Monospace,
                            fontSize = 12.sp
                        )
                    }
                } else {
                    Text(
                        text = "Scan QR code or enter 6-character pairing code from the extension.",
                        color = TextDim,
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace
                    )

                    Button(
                        onClick = onOpenScanner,
                        colors = ButtonDefaults.buttonColors(containerColor = PurpleBrand),
                        shape = RoundedCornerShape(4.dp),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(
                            text = "> scan qr code",
                            color = TextWhite,
                            fontFamily = FontFamily.Monospace,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Bold
                        )
                    }

                    HorizontalDivider(
                        color = BorderSubtle,
                        thickness = 1.dp,
                        modifier = Modifier.padding(vertical = 4.dp)
                    )

                    Text(
                        text = "// or pair manually with code",
                        color = TextMuted,
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace
                    )

                    var manualServerUrl by remember { mutableStateOf("http://192.168.1.5:8000") }
                    var manualCode by remember { mutableStateOf("") }
                    var isClaimingManual by remember { mutableStateOf(false) }
                    var manualError by remember { mutableStateOf<String?>(null) }

                    OutlinedTextField(
                        value = manualServerUrl,
                        onValueChange = { manualServerUrl = it },
                        label = { Text("Server URL", fontFamily = FontFamily.Monospace, fontSize = 11.sp) },
                        singleLine = true,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = PurpleBrand,
                            unfocusedBorderColor = BorderSubtle,
                            focusedTextColor = TextWhite,
                            unfocusedTextColor = TextDim,
                            cursorColor = PurpleLight
                        ),
                        modifier = Modifier.fillMaxWidth(),
                        textStyle = androidx.compose.ui.text.TextStyle(fontFamily = FontFamily.Monospace, fontSize = 12.sp)
                    )

                    OutlinedTextField(
                        value = manualCode,
                        onValueChange = { if (it.length <= 8) manualCode = it.uppercase() },
                        label = { Text("6-Char Code (e.g. 5VQ4TT)", fontFamily = FontFamily.Monospace, fontSize = 11.sp) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = PurpleBrand,
                            unfocusedBorderColor = BorderSubtle,
                            focusedTextColor = GreenNeon,
                            unfocusedTextColor = TextDim,
                            cursorColor = GreenNeon
                        ),
                        modifier = Modifier.fillMaxWidth(),
                        textStyle = androidx.compose.ui.text.TextStyle(
                            fontFamily = FontFamily.Monospace,
                            fontSize = 14.sp,
                            fontWeight = FontWeight.Bold,
                            letterSpacing = 2.sp
                        )
                    )

                    if (manualError != null) {
                        Text(
                            text = "// Error: $manualError",
                            color = StateFailed,
                            fontSize = 11.sp,
                            fontFamily = FontFamily.Monospace
                        )
                    }

                    Button(
                        onClick = {
                            if (manualCode.isBlank()) {
                                manualError = "Please enter pairing code"
                                return@Button
                            }
                            isClaimingManual = true
                            manualError = null

                            coroutineScope.launch {
                                withContext(Dispatchers.IO) {
                                    try {
                                        val token = fcmToken ?: dataStore.getFcmToken()
                                        if (token.isNullOrBlank()) {
                                            withContext(Dispatchers.Main) {
                                                manualError = "FCM token not available"
                                                isClaimingManual = false
                                            }
                                            return@withContext
                                        }

                                        val cleanUrl = manualServerUrl.trim().trimEnd('/')
                                        val cleanCode = manualCode.trim().uppercase()
                                        val endpoint = "$cleanUrl/v1/pairings/$cleanCode/claim"

                                        val client = OkHttpClient.Builder()
                                            .connectTimeout(5, TimeUnit.SECONDS)
                                            .readTimeout(5, TimeUnit.SECONDS)
                                            .build()

                                        val jsonBody = JSONObject().apply {
                                            put("fcm_token", token)
                                        }.toString()

                                        val request = Request.Builder()
                                            .url(endpoint)
                                            .post(jsonBody.toRequestBody("application/json".toMediaType()))
                                            .build()

                                        val response = client.newCall(request).execute()
                                        val respBody = response.body?.string() ?: ""

                                        if (response.isSuccessful) {
                                            val respJson = JSONObject(respBody)
                                            val pairingId = respJson.optString("pairing_id", "")
                                            val respPcName = respJson.optString("pc_name", "Desktop-PC")

                                            dataStore.savePairing(
                                                pairingId = pairingId,
                                                serverUrl = cleanUrl,
                                                pcName = respPcName
                                            )

                                            withContext(Dispatchers.Main) {
                                                isClaimingManual = false
                                                Toast.makeText(context, "Pairing Successful!", Toast.LENGTH_SHORT).show()
                                            }
                                        } else {
                                            withContext(Dispatchers.Main) {
                                                manualError = "Claim failed (${response.code})"
                                                isClaimingManual = false
                                            }
                                        }
                                    } catch (e: Exception) {
                                        withContext(Dispatchers.Main) {
                                            manualError = e.message ?: "Network error"
                                            isClaimingManual = false
                                        }
                                    }
                                }
                            }
                        },
                        enabled = !isClaimingManual,
                        colors = ButtonDefaults.buttonColors(containerColor = BgElevated),
                        border = BorderStroke(1.dp, PurpleLight),
                        shape = RoundedCornerShape(4.dp),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        if (isClaimingManual) {
                            CircularProgressIndicator(
                                color = GreenNeon,
                                strokeWidth = 2.dp,
                                modifier = Modifier.size(14.dp)
                            )
                        } else {
                            Text(
                                text = "> claim code",
                                color = TextWhite,
                                fontFamily = FontFamily.Monospace,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }
                }
            }
        }

        // Active Downloads Card (when paired)
        if (pairingInfo.isPaired) {
            Card(
                colors = CardDefaults.cardColors(containerColor = BgCard),
                border = BorderStroke(1.dp, BorderSubtle),
                shape = RoundedCornerShape(6.dp),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(6.dp)
                        ) {
                            Text(
                                text = "--active",
                                color = PurpleLight,
                                fontWeight = FontWeight.Bold,
                                fontSize = 12.sp,
                                fontFamily = FontFamily.Monospace
                            )
                            Text(
                                text = "downloads",
                                color = TextMuted,
                                fontSize = 11.sp,
                                fontFamily = FontFamily.Monospace
                            )
                        }

                        Surface(
                            shape = RoundedCornerShape(3.dp),
                            color = BgElevated,
                            border = BorderStroke(1.dp, BorderSubtle)
                        ) {
                            Text(
                                text = "${activeDownloads.size}",
                                color = GreenNeon,
                                fontSize = 10.sp,
                                fontWeight = FontWeight.Bold,
                                fontFamily = FontFamily.Monospace,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                            )
                        }
                    }

                    if (activeDownloads.isEmpty()) {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .background(BgInput, RoundedCornerShape(4.dp))
                                .padding(12.dp),
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                text = "// no transfers in progress",
                                color = TextMuted,
                                fontSize = 11.sp,
                                fontFamily = FontFamily.Monospace
                            )
                        }
                    } else {
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            activeDownloads.forEach { dl ->
                                DownloadItemCard(dl)
                            }
                        }
                    }

                    // Clear Notifications Button
                    Button(
                        onClick = {
                            notificationHelper.cancelAll()
                            DownloadRepository.clear()
                            Toast.makeText(context, "Notifications cleared", Toast.LENGTH_SHORT).show()
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = BgElevated),
                        border = BorderStroke(1.dp, BorderSubtle),
                        shape = RoundedCornerShape(4.dp),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(
                            text = "> clear notifications",
                            color = TextDim,
                            fontFamily = FontFamily.Monospace,
                            fontSize = 11.sp
                        )
                    }
                }
            }
        }

        // FCM Device Token Card (Dev / Diagnostic)
        Card(
            colors = CardDefaults.cardColors(containerColor = BgCard),
            border = BorderStroke(1.dp, BorderSubtle),
            shape = RoundedCornerShape(6.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "--fcm [ device_token ]",
                        color = PurpleLight,
                        fontWeight = FontWeight.Bold,
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace
                    )
                    Text(
                        text = "READY",
                        color = GreenNeon,
                        fontSize = 10.sp,
                        fontFamily = FontFamily.Monospace
                    )
                }

                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(BgInput, RoundedCornerShape(4.dp))
                        .padding(10.dp)
                ) {
                    Text(
                        text = fcmToken ?: "Fetching...",
                        color = TextDim,
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace
                    )
                }

                Button(
                    onClick = {
                        fcmToken?.let { token ->
                            val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                            clipboard.setPrimaryClip(ClipData.newPlainText("FCM Token", token))
                            Toast.makeText(context, "FCM Token copied to clipboard", Toast.LENGTH_SHORT).show()
                        }
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = BgElevated),
                    border = BorderStroke(1.dp, PurpleBrand),
                    shape = RoundedCornerShape(4.dp),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(
                        text = "> copy fcm token",
                        color = TextWhite,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 12.sp
                    )
                }
            }
        }

        // Test Notification Diagnostics Card
        Card(
            colors = CardDefaults.cardColors(containerColor = BgCard),
            border = BorderStroke(1.dp, BorderSubtle),
            shape = RoundedCornerShape(6.dp),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    text = "--diagnostics [ local_test ]",
                    color = PurpleLight,
                    fontWeight = FontWeight.Bold,
                    fontSize = 12.sp,
                    fontFamily = FontFamily.Monospace
                )
                Text(
                    text = "Trigger local notifications directly on this device to verify system channels and lock-screen visibility.",
                    color = TextDim,
                    fontSize = 12.sp,
                    fontFamily = FontFamily.Monospace
                )

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Button(
                        onClick = {
                            notificationHelper.showProgressNotification(
                                downloadId = "test-demo-1",
                                filename = "ubuntu-24.04-desktop.iso",
                                percentage = 42.5f,
                                speedBytesSec = 15_500_000,
                                etaSeconds = 180,
                                source = "Chrome",
                                pcName = "Desktop-PC"
                            )
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = BgElevated),
                        border = BorderStroke(1.dp, BorderSubtle),
                        shape = RoundedCornerShape(4.dp),
                        modifier = Modifier.weight(1f)
                    ) {
                        Text(
                            text = "Test 42%",
                            color = GreenNeon,
                            fontFamily = FontFamily.Monospace,
                            fontSize = 11.sp
                        )
                    }

                    Button(
                        onClick = {
                            notificationHelper.showCompletionNotification(
                                downloadId = "test-demo-1",
                                filename = "ubuntu-24.04-desktop.iso",
                                success = true,
                                source = "Chrome",
                                pcName = "Desktop-PC"
                            )
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = BgElevated),
                        border = BorderStroke(1.dp, BorderSubtle),
                        shape = RoundedCornerShape(4.dp),
                        modifier = Modifier.weight(1f)
                    ) {
                        Text(
                            text = "Test Done",
                            color = PurpleLight,
                            fontFamily = FontFamily.Monospace,
                            fontSize = 11.sp
                        )
                    }
                }
            }
        }

        // Footer info
        Text(
            text = "// scan extension qr to pair or use tools/fcm_test_sender.py",
            color = TextMuted,
            fontSize = 11.sp,
            fontFamily = FontFamily.Monospace,
            modifier = Modifier.padding(vertical = 8.dp)
        )
    }
}

@Composable
fun DownloadItemCard(dl: AppDownloadItem) {
    val totalKnown = dl.totalBytes != null && dl.totalBytes > 0
    val currentMB = String.format("%.1f", dl.bytesDownloaded / (1024.0 * 1024.0))
    val totalMB = if (totalKnown) String.format("%.1f", dl.totalBytes!! / (1024.0 * 1024.0)) else "?"
    val pctFloat = dl.percentage ?: if (totalKnown) ((dl.bytesDownloaded.toFloat() / dl.totalBytes!!) * 100f) else null
    val pctProgress = (pctFloat ?: 0f) / 100f

    val stateColor = when (dl.state.lowercase()) {
        "downloading" -> GreenNeon
        "completed" -> PurpleLight
        "paused" -> StatePaused
        "failed" -> StateFailed
        else -> TextDim
    }

    val stateBg = when (dl.state.lowercase()) {
        "downloading" -> GreenDim
        "completed" -> PurpleBrand.copy(alpha = 0.2f)
        "paused" -> StatePaused.copy(alpha = 0.15f)
        "failed" -> StateFailed.copy(alpha = 0.15f)
        else -> BgElevated
    }

    Surface(
        color = BgElevated,
        shape = RoundedCornerShape(4.dp),
        border = BorderStroke(1.dp, BorderSubtle),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(
            modifier = Modifier.padding(10.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = dl.filename,
                    color = TextWhite,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 12.sp,
                    fontFamily = FontFamily.Monospace,
                    modifier = Modifier.weight(1f),
                    maxLines = 1
                )
                Surface(
                    shape = RoundedCornerShape(3.dp),
                    color = stateBg,
                    border = BorderStroke(1.dp, stateColor.copy(alpha = 0.4f))
                ) {
                    Text(
                        text = dl.state.uppercase(),
                        color = stateColor,
                        fontSize = 9.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace,
                        modifier = Modifier.padding(horizontal = 5.dp, vertical = 2.dp)
                    )
                }
            }

            // Progress Bar
            if (pctFloat != null) {
                LinearProgressIndicator(
                    progress = { pctProgress.coerceIn(0f, 1f) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(4.dp),
                    color = GreenNeon,
                    trackColor = BgInput
                )
            } else {
                LinearProgressIndicator(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(4.dp),
                    color = GreenNeon,
                    trackColor = BgInput
                )
            }

            // Stats row
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = "${currentMB}MB / ${totalMB}MB",
                    color = TextDim,
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace
                )
                Text(
                    text = if (pctFloat != null) "${String.format("%.1f", pctFloat)}%" else "LIVE",
                    color = GreenNeon,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold,
                    fontFamily = FontFamily.Monospace
                )
            }
        }
    }
}
