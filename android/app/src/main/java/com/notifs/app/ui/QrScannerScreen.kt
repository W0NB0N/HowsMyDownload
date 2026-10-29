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
import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
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
            .background(HmdColors.Frame)
    ) {
        // Header
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp, vertical = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.Bottom
        ) {
            Column(
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.weight(1f)
            ) {
                Text(
                    text = "$ how's my download // qr",
                    color = HmdColors.OnFrame,
                    fontFamily = JBMono,
                    fontSize = 12.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    text = "SCAN ONCE.",
                    color = HmdColors.Fg,
                    fontFamily = Shoulders,
                    fontWeight = FontWeight.Black,
                    fontSize = 52.sp,
                    style = TextStyle(
                        lineHeight = 44.7.sp,
                        platformStyle = PlatformTextStyle(includeFontPadding = false),
                        lineHeightStyle = LineHeightStyle(LineHeightStyle.Alignment.Center, LineHeightStyle.Trim.Both)
                    ),
                    maxLines = 1
                )
            }

            TerminalButton(
                text = "cancel",
                onClick = onDismiss,
                prompt = "<",
                height = 44.dp,
                fontSize = 13f,
                background = HmdColors.Bg
            )
        }

        // Camera Preview with HUD
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .padding(start = 10.dp, end = 10.dp, bottom = 10.dp)
                .clip(RoundedCornerShape(HmdShape.Radius))
                .background(Color(0xFF050507))
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f)
                    .background(Color(0xFF0B0B10)),
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

                    LiveTag(Modifier.align(Alignment.TopEnd).padding(14.dp))

                    // Viewfinder HUD Overlay
                    Viewfinder(Modifier.size(252.dp))

                    if (isProcessing) {
                        Box(
                            modifier = Modifier
                                .fillMaxSize()
                                .background(Color(0xAA09090C)),
                            contentAlignment = Alignment.Center
                        ) {
                            CircularProgressIndicator(color = HmdColors.Signal, strokeWidth = 3.dp)
                        }
                    }
                } else {
                    Column(
                        modifier = Modifier
                            .padding(16.dp)
                            .background(HmdColors.Surface, RoundedCornerShape(HmdShape.Radius))
                            .border(1.dp, HmdColors.Warn, RoundedCornerShape(HmdShape.Radius))
                            .padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text(
                            "Camera permission required to scan QR code.",
                            color = HmdColors.Muted,
                            fontFamily = JBMono,
                            fontSize = 12.sp
                        )
                        TerminalButton(
                            text = "grant permission",
                            onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) },
                            tone = HmdColors.Warn
                        )
                    }
                }
            }

            // Footer status / hint bar
            Box(Modifier.fillMaxWidth().height(1.dp).background(HmdColors.Line))
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(HmdColors.Surface)
                    .padding(horizontal = 16.dp, vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(14.dp)
            ) {
                Sammy(SammyPose.CarryQr, 63.dp, contentDescription = "Sammy holding up a QR code")
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row {
                        Text(
                            text = "// $statusMessage",
                            color = if (isProcessing) HmdColors.Signal else HmdColors.Fg,
                            fontSize = 13.sp,
                            fontWeight = FontWeight.Bold,
                            lineHeight = 18.sp,
                            fontFamily = JBMono,
                            modifier = Modifier.weight(1f, fill = false)
                        )
                        BlinkingCaret()
                    }
                    Text(
                        text = buildAnnotatedString {
                            append("Extension › ")
                            withStyle(SpanStyle(color = HmdColors.Flag)) { append("pair device") }
                            append(". The key in the QR never touches the server.")
                        },
                        color = HmdColors.Muted,
                        fontSize = 12.sp,
                        lineHeight = 18.sp,
                        fontFamily = JBMono
                    )
                }
            }
        }
    }
}

/** Green corner brackets, a faint frame and a scan line sweeping top to bottom (2.4 s). */
@Composable
private fun Viewfinder(modifier: Modifier = Modifier) {
    val still = rememberReducedMotion()
    val sweep = if (still) 0.5f else {
        val t by rememberInfiniteTransition(label = "scan").animateFloat(
            initialValue = 0.06f, targetValue = 0.92f,
            animationSpec = infiniteRepeatable(
                tween(1200, easing = CubicBezierEasing(0.45f, 0f, 0.55f, 1f)),
                repeatMode = RepeatMode.Reverse
            ),
            label = "scanY"
        )
        t
    }
    Canvas(modifier) {
        val edge = 5.dp.toPx()
        val arm = 36.dp.toPx()
        val out = 2.dp.toPx()
        drawRect(color = HmdColors.Signal.copy(alpha = 0.04f))
        drawRect(
            color = HmdColors.Signal.copy(alpha = 0.18f),
            style = androidx.compose.ui.graphics.drawscope.Stroke(width = 1.dp.toPx())
        )
        // Corners: a horizontal and a vertical bar each, 2 dp outside the frame
        val w = size.width
        val h = size.height
        listOf(
            Offset(-out, -out) to Offset(1f, 1f),
            Offset(w + out, -out) to Offset(-1f, 1f),
            Offset(-out, h + out) to Offset(1f, -1f),
            Offset(w + out, h + out) to Offset(-1f, -1f)
        ).forEach { (corner, dir) ->
            val x0 = if (dir.x > 0) corner.x else corner.x - arm
            val y0 = if (dir.y > 0) corner.y else corner.y - edge
            drawRect(HmdColors.Signal, topLeft = Offset(x0, y0), size = Size(arm, edge))
            val vx = if (dir.x > 0) corner.x else corner.x - edge
            val vy = if (dir.y > 0) corner.y else corner.y - arm
            drawRect(HmdColors.Signal, topLeft = Offset(vx, vy), size = Size(edge, arm))
        }
        // Scan line with a soft glow
        val inset = 12.dp.toPx()
        val y = h * sweep
        val glow = 12.dp.toPx()
        drawRect(
            brush = Brush.verticalGradient(
                listOf(Color.Transparent, HmdColors.Signal.copy(alpha = 0.35f), Color.Transparent),
                startY = y - glow, endY = y + glow
            ),
            topLeft = Offset(inset, y - glow),
            size = Size(w - inset * 2, glow * 2)
        )
        drawRect(HmdColors.Signal, topLeft = Offset(inset, y - 1.dp.toPx()), size = Size(w - inset * 2, 2.dp.toPx()))
    }
}

@Composable
private fun LiveTag(modifier: Modifier = Modifier) {
    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        BlinkingCaret(square = true)
        Text(
            text = "LIVE",
            color = HmdColors.Signal,
            fontSize = 11.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 0.1.em,
            fontFamily = JBMono
        )
    }
}

/** Terminal caret blinking with steps(1) over 1 s: a purple "_" or a green square. */
@Composable
private fun BlinkingCaret(square: Boolean = false) {
    val still = rememberReducedMotion()
    val visible = if (still) true else {
        val phase by rememberInfiniteTransition(label = "caret").animateValue(
            initialValue = 0, targetValue = 2, typeConverter = Int.VectorConverter,
            animationSpec = infiniteRepeatable(tween(1000, easing = LinearEasing)),
            label = "caretPhase"
        )
        phase == 0
    }
    if (square) {
        Box(Modifier.size(6.dp).alpha(if (visible) 1f else 0f).background(HmdColors.Signal))
    } else {
        Text(
            text = "_",
            color = HmdColors.Flag,
            fontSize = 13.sp,
            fontWeight = FontWeight.Bold,
            fontFamily = JBMono,
            modifier = Modifier.alpha(if (visible) 1f else 0f)
        )
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
