package com.notifs.app.ui

import android.Manifest
import android.content.pm.PackageManager
import android.util.Log
import android.view.ViewGroup
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.annotation.OptIn
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.common.InputImage
import com.notifs.app.BuildConfig
import com.notifs.app.data.PairingDataStore
import com.notifs.app.ui.theme.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import com.notifs.app.data.PairingApi
import com.notifs.app.util.CryptoUtils
import org.json.JSONObject
import java.util.concurrent.Executors

@Composable
fun QrScannerScreen(
    dataStore: PairingDataStore,
    fcmToken: String?,
    onDismiss: () -> Unit,
    onPairSuccess: () -> Unit
) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    var isProcessing by remember { mutableStateOf(false) }
    var lastAttemptTimestamp by remember { mutableLongStateOf(0L) }
    var statusMessage by remember { mutableStateOf("Align QR code inside viewfinder") }
    var hasCameraPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        )
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { granted ->
        hasCameraPermission = granted
    }

    LaunchedEffect(Unit) {
        if (!hasCameraPermission) {
            permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(BgCanvas)
            .padding(16.dp),
        verticalArrangement = Arrangement.SpaceBetween
    ) {
        // Header
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .weight(1f)
                    .padding(end = 8.dp)
            ) {
                Text("$ ", color = PurpleLight, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, fontSize = 15.sp)
                Text(
                    text = "how's my download",
                    color = TextWhite,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                    fontSize = 15.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(" // qr", color = TextMuted, fontFamily = FontFamily.Monospace, fontSize = 13.sp)
            }

            Button(
                onClick = onDismiss,
                colors = ButtonDefaults.buttonColors(containerColor = BgElevated),
                border = BorderStroke(1.dp, BorderSubtle),
                shape = RoundedCornerShape(4.dp),
                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)
            ) {
                Text("cancel", color = TextDim, fontFamily = FontFamily.Monospace, fontSize = 11.sp)
            }
        }

        // Camera Preview with HUD
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .padding(vertical = 16.dp),
            contentAlignment = Alignment.Center
        ) {
            if (hasCameraPermission) {
                CameraPreviewView(
                    onQrScanned = { rawQrText ->
                        val now = System.currentTimeMillis()
                        if (!isProcessing && (now - lastAttemptTimestamp > 3000L)) {
                            isProcessing = true
                            lastAttemptTimestamp = now
                            statusMessage = "Claiming pairing code..."
                            coroutineScope.launch {
                                handleQrPayload(
                                    rawText = rawQrText,
                                    fcmToken = fcmToken,
                                    dataStore = dataStore,
                                    onSuccess = {
                                        Toast.makeText(context, "Pairing Successful!", Toast.LENGTH_SHORT).show()
                                        onPairSuccess()
                                    },
                                    onError = { err ->
                                        statusMessage = "Error: $err"
                                        isProcessing = false
                                        lastAttemptTimestamp = System.currentTimeMillis()
                                    }
                                )
                            }
                        }
                    }
                )

                // Viewfinder HUD Overlay
                Canvas(modifier = Modifier.size(240.dp)) {
                    val strokeW = 3.dp.toPx()
                    val cornerLen = 24.dp.toPx()

                    // Center box border
                    drawRect(
                        color = Color(0x3361CF92),
                        size = Size(size.width, size.height),
                        style = Stroke(width = 1.dp.toPx())
                    )

                    // Top-Left Corner
                    drawLine(color = GreenNeon, start = Offset(0f, 0f), end = Offset(cornerLen, 0f), strokeWidth = strokeW)
                    drawLine(color = GreenNeon, start = Offset(0f, 0f), end = Offset(0f, cornerLen), strokeWidth = strokeW)

                    // Top-Right Corner
                    drawLine(color = GreenNeon, start = Offset(size.width, 0f), end = Offset(size.width - cornerLen, 0f), strokeWidth = strokeW)
                    drawLine(color = GreenNeon, start = Offset(size.width, 0f), end = Offset(size.width, cornerLen), strokeWidth = strokeW)

                    // Bottom-Left Corner
                    drawLine(color = GreenNeon, start = Offset(0f, size.height), end = Offset(cornerLen, size.height), strokeWidth = strokeW)
                    drawLine(color = GreenNeon, start = Offset(0f, size.height), end = Offset(0f, size.height - cornerLen), strokeWidth = strokeW)

                    // Bottom-Right Corner
                    drawLine(color = GreenNeon, start = Offset(size.width, size.height), end = Offset(size.width - cornerLen, size.height), strokeWidth = strokeW)
                    drawLine(color = GreenNeon, start = Offset(size.width, size.height), end = Offset(size.width, size.height - cornerLen), strokeWidth = strokeW)
                }

                if (isProcessing) {
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .background(Color(0xAA09090C)),
                        contentAlignment = Alignment.Center
                    ) {
                        CircularProgressIndicator(color = GreenNeon, strokeWidth = 3.dp)
                    }
                }
            } else {
                Card(
                    colors = CardDefaults.cardColors(containerColor = BgCard),
                    border = BorderStroke(1.dp, StatePaused),
                    shape = RoundedCornerShape(6.dp)
                ) {
                    Column(
                        modifier = Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text("Camera permission required to scan QR code.", color = TextDim, fontFamily = FontFamily.Monospace, fontSize = 12.sp)
                        Button(
                            onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) },
                            colors = ButtonDefaults.buttonColors(containerColor = PurpleBrand),
                            shape = RoundedCornerShape(4.dp)
                        ) {
                            Text("Grant Permission", fontFamily = FontFamily.Monospace, fontSize = 12.sp)
                        }
                    }
                }
            }
        }

        // Footer status text
        Surface(
            color = BgElevated,
            shape = RoundedCornerShape(4.dp),
            border = BorderStroke(1.dp, BorderSubtle),
            modifier = Modifier.fillMaxWidth()
        ) {
            Text(
                text = "// $statusMessage",
                color = if (isProcessing) GreenNeon else TextDim,
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace,
                modifier = Modifier.padding(10.dp)
            )
        }
    }
}

@OptIn(ExperimentalGetImage::class)
@Composable
private fun CameraPreviewView(onQrScanned: (String) -> Unit) {
    val lifecycleOwner = LocalLifecycleOwner.current
    val cameraExecutor = remember { Executors.newSingleThreadExecutor() }
    val scanner = remember { BarcodeScanning.getClient() }

    AndroidView(
        modifier = Modifier.fillMaxSize(),
        factory = { ctx ->
            PreviewView(ctx).apply {
                layoutParams = ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT
                )
                scaleType = PreviewView.ScaleType.FILL_CENTER

                val cameraProviderFuture = ProcessCameraProvider.getInstance(ctx)
                cameraProviderFuture.addListener({
                    val cameraProvider = cameraProviderFuture.get()
                    val preview = Preview.Builder().build().also {
                        it.setSurfaceProvider(surfaceProvider)
                    }

                    val imageAnalysis = ImageAnalysis.Builder()
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                        .build()

                    imageAnalysis.setAnalyzer(cameraExecutor) { imageProxy ->
                        val mediaImage = imageProxy.image
                        if (mediaImage != null) {
                            val image = InputImage.fromMediaImage(mediaImage, imageProxy.imageInfo.rotationDegrees)
                            scanner.process(image)
                                .addOnSuccessListener { barcodes ->
                                    for (barcode in barcodes) {
                                        barcode.rawValue?.let { raw ->
                                            onQrScanned(raw)
                                        }
                                    }
                                }
                                .addOnCompleteListener {
                                    imageProxy.close()
                                }
                        } else {
                            imageProxy.close()
                        }
                    }

                    try {
                        cameraProvider.unbindAll()
                        cameraProvider.bindToLifecycle(
                            lifecycleOwner,
                            CameraSelector.DEFAULT_BACK_CAMERA,
                            preview,
                            imageAnalysis
                        )
                    } catch (e: Exception) {
                        Log.e("QrScannerScreen", "Camera binding failed", e)
                    }
                }, ContextCompat.getMainExecutor(ctx))
            }
        }
    )

    DisposableEffect(Unit) {
        onDispose {
            cameraExecutor.shutdown()
        }
    }
}

private suspend fun handleQrPayload(
    rawText: String,
    fcmToken: String?,
    dataStore: PairingDataStore,
    onSuccess: () -> Unit,
    onError: (String) -> Unit
) {
    withContext(Dispatchers.IO) {
        var serverUrl = ""
        var code = ""
        var pcName = "Desktop-PC"
        var encryptionKey: String? = null
        try {

            if (rawText.trim().startsWith("{")) {
                val json = JSONObject(rawText)
                serverUrl = json.optString("server_url", BuildConfig.DEFAULT_SERVER_URL)
                code = json.optString("code", "")
                pcName = json.optString("pc_name", "Desktop-PC")
                if (json.has("enc_key") && !json.isNull("enc_key")) {
                    encryptionKey = json.getString("enc_key").trim()
                }
            } else if (rawText.contains("|")) {
                val parts = rawText.split("|")
                serverUrl = parts[0]
                code = parts[1]
                if (parts.size > 2) pcName = parts[2]
                if (parts.size > 3) encryptionKey = parts[3].trim()
            } else {
                code = rawText.trim()
                serverUrl = BuildConfig.DEFAULT_SERVER_URL
            }

            if (code.isBlank()) {
                withContext(Dispatchers.Main) { onError("Invalid QR code payload") }
                return@withContext
            }
            if (encryptionKey != null && !CryptoUtils.isValidKeyHex(encryptionKey)) {
                // A corrupted key would make every filename undecryptable: refuse to pair
                withContext(Dispatchers.Main) { onError("QR code has an invalid encryption key") }
                return@withContext
            }

            val token = fcmToken ?: dataStore.getFcmToken()
            if (token.isNullOrBlank()) {
                withContext(Dispatchers.Main) { onError("FCM Token not available yet") }
                return@withContext
            }

            val cleanUrl = serverUrl.trim().trimEnd('/')
            val result = PairingApi.claim(cleanUrl, code, token)
            dataStore.savePairing(
                pairingId = result.pairingId,
                serverUrl = cleanUrl,
                pcName = result.pcName.ifBlank { pcName },
                deviceSecret = result.deviceSecret,
                encryptionKey = encryptionKey?.lowercase()
            )

            withContext(Dispatchers.Main) {
                onSuccess()
            }
        } catch (e: PairingApi.ApiException) {
            withContext(Dispatchers.Main) {
                onError(e.message ?: "Claim failed (${e.code})")
            }
        } catch (e: Exception) {
            val msg = e.message ?: "Network error"
            val displayMsg = if ((msg.contains("Failed to connect", ignoreCase = true) || msg.contains("Connection refused", ignoreCase = true)) && 
                (serverUrl.contains("localhost") || serverUrl.contains("127.0.0.1"))) {
                "Cannot reach localhost from phone. Set PC IP or run 'adb reverse tcp:8000 tcp:8000'"
            } else {
                msg
            }
            withContext(Dispatchers.Main) {
                onError(displayMsg)
            }
        }
    }
}
