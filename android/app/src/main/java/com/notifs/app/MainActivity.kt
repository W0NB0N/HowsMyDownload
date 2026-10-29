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
import androidx.activity.SystemBarStyle
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import androidx.compose.ui.zIndex
import androidx.core.content.ContextCompat
import com.google.firebase.messaging.FirebaseMessaging
import com.notifs.app.data.AppDownloadItem
import com.notifs.app.data.DownloadRepository
import com.notifs.app.data.PairingApi
import com.notifs.app.data.PairingDataStore
import com.notifs.app.data.PairingInfo
import com.notifs.app.data.PendingCommand
import com.notifs.app.service.DownloadCommands
import com.notifs.app.service.NotifFcmService
import com.notifs.app.service.NotificationHelper
import com.notifs.app.service.StaleWatchdog
import com.notifs.app.ui.*
import com.notifs.app.ui.theme.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextOverflow
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale

class MainActivity : ComponentActivity() {

    private lateinit var notificationHelper: NotificationHelper
    private lateinit var dataStore: PairingDataStore

    override fun onCreate(savedInstanceState: Bundle?) {
        // The purple frame runs under the system bars; light icons on it
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT)
        )
        super.onCreate(savedInstanceState)
        notificationHelper = NotificationHelper(this)
        dataStore = PairingDataStore(this)

        setContent {
            DownloadNotifsTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = HmdColors.Frame
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

                    Box(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing)) {
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
}

/**
 * The state a download card shows. A transfer with no push for [StaleWatchdog.TIMEOUT_MS] reads
 * as "offline", the same rule that fires the "PC offline" notification.
 */
internal fun displayState(dl: AppDownloadItem, now: Long): String {
    val state = dl.state.lowercase()
    return when {
        state == "stale" -> "offline"
        state == "downloading" && now - dl.updatedAt > StaleWatchdog.TIMEOUT_MS -> "offline"
        else -> state
    }
}

internal fun poseFor(state: String): SammyPose = when (state) {
    "starting" -> SammyPose.Starting
    "downloading" -> SammyPose.Downloading
    "paused" -> SammyPose.Paused
    "completed" -> SammyPose.Completed
    "failed" -> SammyPose.Failed
    else -> SammyPose.Offline
}

/** Header pose: unpaired › a fresh completion (4 s) › downloading › starting › paused › idle. */
internal fun heroPose(isPaired: Boolean, states: List<String>, celebrating: Boolean): SammyPose = when {
    !isPaired -> SammyPose.Think
    states.isEmpty() -> SammyPose.Wave
    celebrating && "completed" in states -> SammyPose.Completed
    "downloading" in states -> SammyPose.Downloading
    "starting" in states -> SammyPose.Starting
    "paused" in states -> SammyPose.Paused
    else -> SammyPose.Chill
}

private fun formatSpeed(bytesPerSec: Long): String = when {
    bytesPerSec >= 1024 * 1024 -> String.format(Locale.US, "%.1f MB/s", bytesPerSec / (1024.0 * 1024.0))
    bytesPerSec >= 1024 -> String.format(Locale.US, "%.0f KB/s", bytesPerSec / 1024.0)
    else -> "$bytesPerSec B/s"
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
    val pendingCommands by DownloadRepository.pendingFlow.collectAsState()
    val commandFailures by DownloadRepository.failuresFlow.collectAsState()
    val isPrivacyOn by dataStore.hideFilenamesFlow.collectAsState(initial = false)
    var confirmRestart by remember { mutableStateOf<AppDownloadItem?>(null) }
    var unpairedFrom by remember { mutableStateOf<String?>(null) }
    var tokenCopied by remember { mutableStateOf(false) }

    val sendCommand: (AppDownloadItem, DownloadCommands.Action) -> Unit = { dl, action ->
        coroutineScope.launch {
            val result = withContext(Dispatchers.IO) {
                DownloadCommands.dispatch(context.applicationContext, dl.id, action, dl.state)
            }
            if (result is DownloadCommands.SendResult.Failed) {
                Toast.makeText(context, result.message, Toast.LENGTH_SHORT).show()
            }
        }
    }
    val onCommand: (AppDownloadItem, DownloadCommands.Action) -> Unit = { dl, action ->
        if (DownloadCommands.needsConfirmation(action, dl.state)) {
            confirmRestart = dl
        } else {
            sendCommand(dl, action)
        }
    }

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

    // Display only: a clock for the "PC offline" card state, and the header's 4 s completion pose
    val now by produceState(System.currentTimeMillis()) {
        while (true) {
            delay(5_000)
            value = System.currentTimeMillis()
        }
    }
    val shownStates = activeDownloads.map { displayState(it, now) }
    val completedIds = activeDownloads.filter { it.state.lowercase() == "completed" }.map { it.id }.toSet()
    var seenCompleted by remember { mutableStateOf(emptySet<String>()) }
    var celebrating by remember { mutableStateOf(false) }
    LaunchedEffect(completedIds) {
        val fresh = completedIds.any { it !in seenCompleted }
        seenCompleted = completedIds
        if (fresh) {
            celebrating = true
            try {
                delay(4_000)
            } finally {
                celebrating = false
            }
        }
    }
    LaunchedEffect(unpairedFrom) {
        if (unpairedFrom != null) {
            delay(2_800)
            unpairedFrom = null
        }
    }
    LaunchedEffect(tokenCopied) {
        if (tokenCopied) {
            delay(1_600)
            tokenCopied = false
        }
    }

    Box(Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
        ) {
            HomeHeader(
                hasNotifPermission = hasNotifPermission,
                pose = heroPose(pairingInfo.isPaired, shownStates, celebrating),
                modifier = Modifier.zIndex(1f)
            )

            Column(
                modifier = Modifier
                    .padding(start = 10.dp, end = 10.dp, bottom = 10.dp)
                    .fillMaxWidth()
                    .background(HmdColors.Bg, RoundedCornerShape(HmdShape.Radius))
                    .padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                // Permission Card (if needed)
                if (!hasNotifPermission && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    SectionCard(border = HmdColors.Warn) {
                        Text(
                            text = "--permission [ POST_NOTIFICATIONS ]",
                            color = HmdColors.Warn,
                            fontWeight = FontWeight.Bold,
                            fontSize = 13.sp,
                            fontFamily = JBMono
                        )
                        Text(
                            text = "Notifications are required to show real-time lock-screen download progress bars.",
                            color = HmdColors.Muted,
                            fontSize = 12.sp,
                            lineHeight = 18.sp,
                            fontFamily = JBMono
                        )
                        TerminalButton(
                            text = "grant permission",
                            onClick = { permissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS) },
                            tone = HmdColors.Warn,
                            modifier = Modifier.fillMaxWidth()
                        )
                    }
                }

                // Pairing Status Card
                SectionCard(
                    border = if (pairingInfo.isPaired) HmdColors.SignalDeepBorder else Color(0xFF4B2A73),
                    gap = if (pairingInfo.isPaired) 14.dp else 16.dp
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        SectionLabel("--pairing", "[ pc_relay ]")
                        if (pairingInfo.isPaired) {
                            Badge("Paired", Badges.Downloading)
                        } else {
                            Badge("Unpaired", Badges.Offline)
                        }
                    }

                    if (pairingInfo.isPaired) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(12.dp)
                        ) {
                            Sammy(SammyPose.Laptop, 49.dp, contentDescription = "Sammy typing at a laptop")
                            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                Text(
                                    text = "PC",
                                    color = HmdColors.Faint,
                                    fontSize = 11.sp,
                                    letterSpacing = 0.08.em,
                                    fontFamily = JBMono
                                )
                                Text(
                                    text = (pairingInfo.pcName ?: "Desktop-PC").uppercase(),
                                    color = HmdColors.Fg,
                                    fontSize = 34.sp,
                                    fontFamily = Shoulders,
                                    fontWeight = FontWeight.Black,
                                    style = TightDisplay.copy(lineHeight = 31.sp),
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis
                                )
                            }
                        }
                        Text(
                            text = buildAnnotatedString {
                                append("server ")
                                withStyle(SpanStyle(color = HmdColors.Faint)) { append("·") }
                                append(" ")
                                append((pairingInfo.serverUrl ?: BuildConfig.DEFAULT_SERVER_URL).substringAfter("://").trimEnd('/'))
                            },
                            color = HmdColors.Muted,
                            fontSize = 12.sp,
                            fontFamily = JBMono
                        )
                        if (!pairingInfo.hasDeviceSecret) {
                            Text(
                                text = "! legacy pairing: unpair and scan a new QR so this phone can refresh its token",
                                color = HmdColors.Warn,
                                fontSize = 11.sp,
                                lineHeight = 16.sp,
                                fontFamily = JBMono
                            )
                        }

                        TerminalButton(
                            text = "unpair pc",
                            onClick = {
                                coroutineScope.launch {
                                    val sUrl = pairingInfo.serverUrl
                                    val pId = pairingInfo.pairingId
                                    val pcName = pairingInfo.pcName ?: "Desktop-PC"
                                    withContext(Dispatchers.IO) {
                                        val deviceSecret = dataStore.getDeviceSecret()
                                        if (!sUrl.isNullOrBlank() && !pId.isNullOrBlank() && !deviceSecret.isNullOrBlank()) {
                                            // Best effort: local state is cleared even if offline
                                            try {
                                                PairingApi.unpair(sUrl, pId, deviceSecret)
                                            } catch (_: Exception) {}
                                        }
                                    }
                                    dataStore.clearPairing()
                                    NotifFcmService.resetState(context)
                                    notificationHelper.cancelAll()
                                    DownloadRepository.clear()
                                    unpairedFrom = pcName
                                }
                            },
                            tone = HmdColors.Fail,
                            textColor = HmdColors.Fail,
                            modifier = Modifier.fillMaxWidth()
                        )
                    } else {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(14.dp)
                        ) {
                            Sammy(SammyPose.CarryQr, 84.dp, contentDescription = "Sammy holding up a QR code")
                            Text(
                                text = buildAnnotatedString {
                                    append("Scan the QR from ")
                                    withStyle(SpanStyle(color = HmdColors.Fg, fontWeight = FontWeight.Bold)) { append("pair device") }
                                    append(" in the extension. One scan, about two seconds.")
                                },
                                color = Color(0xFFD4D4D8),
                                fontSize = 13.sp,
                                lineHeight = 21.sp,
                                fontFamily = JBMono
                            )
                        }

                        CtaButton(text = "Scan QR code", onClick = onOpenScanner)

                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(10.dp)
                        ) {
                            Box(Modifier.weight(1f).height(1.dp).background(HmdColors.Line))
                            Text(
                                text = "// or pair with a code",
                                color = HmdColors.Faint,
                                fontSize = 12.sp,
                                fontFamily = JBMono
                            )
                            Box(Modifier.weight(1f).height(1.dp).background(HmdColors.Line))
                        }

                        var manualCode by remember { mutableStateOf("") }
                        var isClaimingManual by remember { mutableStateOf(false) }
                        var manualError by remember { mutableStateOf<String?>(null) }

                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(
                                text = "6-CHARACTER CODE",
                                color = HmdColors.Faint,
                                fontSize = 11.sp,
                                letterSpacing = 0.08.em,
                                fontFamily = JBMono
                            )
                            PairingCodeField(
                                value = manualCode,
                                onValueChange = { if (it.length <= 8) manualCode = it.uppercase() }
                            )
                        }

                        if (manualError != null) {
                            Text(
                                text = "// Error: $manualError",
                                color = HmdColors.Fail,
                                fontSize = 11.sp,
                                fontFamily = JBMono
                            )
                        }

                        TerminalButton(
                            text = "claim code",
                            onClick = {
                                if (manualCode.isBlank()) {
                                    manualError = "Please enter pairing code"
                                    return@TerminalButton
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

                                            val serverTarget = pairingInfo.serverUrl?.takeIf { it.isNotBlank() } ?: BuildConfig.DEFAULT_SERVER_URL
                                            val cleanUrl = serverTarget.trim().trimEnd('/')
                                            // Manual codes carry no encryption key (it only travels in the
                                            // QR), so filenames show as "Encrypted file" on this phone.
                                            val result = PairingApi.claim(cleanUrl, manualCode, token)
                                            dataStore.savePairing(
                                                pairingId = result.pairingId,
                                                serverUrl = cleanUrl,
                                                pcName = result.pcName,
                                                deviceSecret = result.deviceSecret
                                            )

                                            withContext(Dispatchers.Main) {
                                                isClaimingManual = false
                                                Toast.makeText(context, "Paired (scan the QR to see filenames)", Toast.LENGTH_SHORT).show()
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
                            modifier = Modifier.fillMaxWidth(),
                            content = if (isClaimingManual) {
                                {
                                    CircularProgressIndicator(
                                        color = HmdColors.Signal,
                                        strokeWidth = 2.dp,
                                        modifier = Modifier.size(14.dp)
                                    )
                                }
                            } else null
                        )
                    }
                }

                // Active Downloads Card (when paired)
                if (pairingInfo.isPaired) {
                    SectionCard {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            SectionLabel("--active", "downloads")
                            Box(
                                modifier = Modifier
                                    .defaultMinSize(minWidth = 28.dp, minHeight = 28.dp)
                                    .background(HmdColors.Raised, RoundedCornerShape(HmdShape.RadiusSm))
                                    .border(1.dp, HmdColors.LineStrong, RoundedCornerShape(HmdShape.RadiusSm))
                                    .padding(horizontal = 6.dp),
                                contentAlignment = Alignment.Center
                            ) {
                                Text(
                                    text = "${activeDownloads.size}",
                                    color = if (activeDownloads.isEmpty()) HmdColors.Faint else HmdColors.Fg,
                                    fontSize = 13.sp,
                                    fontWeight = FontWeight.Bold,
                                    fontFamily = JBMono
                                )
                            }
                        }

                        if (activeDownloads.isEmpty()) {
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .background(HmdColors.Bg, RoundedCornerShape(HmdShape.Radius))
                                    .dashedBorder(HmdColors.LineStrong)
                                    .padding(start = 16.dp, end = 16.dp, top = 24.dp, bottom = 20.dp),
                                horizontalAlignment = Alignment.CenterHorizontally,
                                verticalArrangement = Arrangement.spacedBy(12.dp)
                            ) {
                                Sammy(SammyPose.Chill, 98.dp, contentDescription = "Sammy sitting back on the grass")
                                Column(
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                    verticalArrangement = Arrangement.spacedBy(4.dp)
                                ) {
                                    Text(
                                        text = "// no transfers in progress",
                                        color = HmdColors.Fg,
                                        fontSize = 13.sp,
                                        fontFamily = JBMono
                                    )
                                    Text(
                                        text = "start a download on ${pairingInfo.pcName ?: "Desktop-PC"}",
                                        color = HmdColors.Faint,
                                        fontSize = 12.sp,
                                        fontFamily = JBMono,
                                        textAlign = TextAlign.Center
                                    )
                                }
                            }
                        } else {
                            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                                activeDownloads.forEachIndexed { i, dl ->
                                    DownloadItemCard(
                                        dl = dl,
                                        shownState = shownStates[i],
                                        pending = pendingCommands[dl.id]?.takeIf { it.fromState == dl.state },
                                        failure = commandFailures[dl.id]?.message,
                                        onCommand = { action -> onCommand(dl, action) }
                                    )
                                }
                            }
                        }

                        // Clear Notifications Button
                        TerminalButton(
                            text = "clear notifications",
                            onClick = {
                                notificationHelper.cancelAll()
                                DownloadRepository.clear()
                                Toast.makeText(context, "Notifications cleared", Toast.LENGTH_SHORT).show()
                            },
                            modifier = Modifier.fillMaxWidth()
                        )
                    }
                }

                // Privacy Guard Card: Content-level filename hiding (shown only in app)
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(HmdColors.Surface, RoundedCornerShape(HmdShape.Radius))
                        .border(1.dp, HmdColors.Line, RoundedCornerShape(HmdShape.Radius))
                        .padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(14.dp)
                ) {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.weight(1f)) {
                        SectionLabel("--privacy", "[ hide_filenames ]")
                        Text(
                            text = "Hide filenames in notifications. Names stay in the app.",
                            color = HmdColors.Muted,
                            fontSize = 12.sp,
                            lineHeight = 18.6.sp,
                            fontFamily = JBMono
                        )
                    }

                    HmdToggle(
                        checked = isPrivacyOn,
                        onCheckedChange = { checked ->
                            coroutineScope.launch {
                                dataStore.setHideFilenames(checked)

                                // Immediately re-render all existing on-screen notifications
                                val currentDownloads = DownloadRepository.downloadsFlow.value
                                val activeOnly = currentDownloads.filter {
                                    it.state.lowercase() in listOf("downloading", "starting", "paused")
                                }

                                if (activeOnly.size >= 3) {
                                    val totalSpeed = activeOnly.filter { it.state != "paused" }.sumOf { it.speedBytesSec }
                                    var remaining = 0L
                                    var hasRem = false
                                    for (dl in activeOnly) {
                                        if (dl.totalBytes != null && dl.totalBytes > dl.bytesDownloaded) {
                                            remaining += (dl.totalBytes - dl.bytesDownloaded)
                                            hasRem = true
                                        }
                                    }
                                    notificationHelper.showGroupSummary(
                                        activeCount = activeOnly.size,
                                        totalSpeedBytes = totalSpeed,
                                        totalRemainingBytes = if (hasRem) remaining else null,
                                        activeItems = activeOnly.map { Pair(it.filename, it.percentage) },
                                        pcName = pairingInfo.pcName ?: "Desktop-PC",
                                        hideFilenames = checked
                                    )
                                } else {
                                    notificationHelper.cancelGroupSummary()
                                }

                                for (dl in activeOnly) {
                                    notificationHelper.showProgressNotification(
                                        downloadId = dl.id,
                                        filename = dl.filename,
                                        percentage = dl.percentage,
                                        speedBytesSec = dl.speedBytesSec,
                                        etaSeconds = dl.etaSeconds,
                                        pcName = pairingInfo.pcName ?: "Desktop-PC",
                                        hideFilenames = checked,
                                        state = dl.state
                                    )
                                }
                            }
                        }
                    )
                }

                // FCM Device Token Card (Dev / Diagnostic)
                SectionCard {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        SectionLabel("--fcm", "[ device_token ]")
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(7.dp)
                        ) {
                            BlinkDot(HmdColors.Signal)
                            Text(
                                text = "READY",
                                color = HmdColors.Signal,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                letterSpacing = 0.1.em,
                                fontFamily = JBMono
                            )
                        }
                    }

                    Text(
                        text = fcmToken ?: "Fetching...",
                        color = HmdColors.Muted,
                        fontSize = 11.5.sp,
                        lineHeight = 19.sp,
                        fontFamily = JBMono,
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(HmdColors.Bg, RoundedCornerShape(HmdShape.Radius))
                            .border(1.dp, HmdColors.Line, RoundedCornerShape(HmdShape.Radius))
                            .padding(12.dp)
                    )

                    TerminalButton(
                        text = if (tokenCopied) "copied to clipboard" else "copy fcm token",
                        onClick = {
                            fcmToken?.let { token ->
                                val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                                clipboard.setPrimaryClip(ClipData.newPlainText("FCM Token", token))
                                Toast.makeText(context, "FCM Token copied to clipboard", Toast.LENGTH_SHORT).show()
                                tokenCopied = true
                            }
                        },
                        tone = if (tokenCopied) HmdColors.Signal else HmdColors.Flag,
                        textColor = if (tokenCopied) HmdColors.Signal else HmdColors.Fg,
                        modifier = Modifier.fillMaxWidth()
                    )
                }

                // Footer info
                Text(
                    text = "// how's my download · scan extension qr to pair or enter 6-char code",
                    color = HmdColors.Faint,
                    fontSize = 11.sp,
                    lineHeight = 16.sp,
                    fontFamily = JBMono,
                    modifier = Modifier.padding(horizontal = 4.dp, vertical = 4.dp)
                )
            }
        }

        unpairedFrom?.let { pcName ->
            UnpairedToast(
                pcName = pcName,
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .padding(bottom = 28.dp)
            )
        }
    }

    confirmRestart?.let { dl ->
        AlertDialog(
            onDismissRequest = { confirmRestart = null },
            containerColor = HmdColors.Surface,
            shape = RoundedCornerShape(HmdShape.Radius),
            modifier = Modifier.border(1.dp, HmdColors.LineStrong, RoundedCornerShape(HmdShape.Radius)),
            title = {
                Text(
                    text = "restart download?",
                    color = HmdColors.Fg,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Bold,
                    fontFamily = JBMono
                )
            },
            text = {
                Text(
                    text = "\"${dl.filename}\" starts again from 0%. What's downloaded so far is discarded.",
                    color = HmdColors.Muted,
                    fontSize = 12.sp,
                    lineHeight = 18.sp,
                    fontFamily = JBMono
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    confirmRestart = null
                    sendCommand(dl, DownloadCommands.Action.RESTART)
                }) {
                    Text("> restart", color = HmdColors.Fail, fontFamily = JBMono, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                }
            },
            dismissButton = {
                TextButton(onClick = { confirmRestart = null }) {
                    Text("cancel", color = HmdColors.Muted, fontFamily = JBMono, fontSize = 13.sp)
                }
            }
        )
    }
}

/** Shoulders at line-height 0.86 with the font padding trimmed. */
private val TightDisplay = TextStyle(
    platformStyle = PlatformTextStyle(includeFontPadding = false),
    lineHeightStyle = LineHeightStyle(LineHeightStyle.Alignment.Center, LineHeightStyle.Trim.Both)
)

@Composable
private fun HomeHeader(hasNotifPermission: Boolean, pose: SammyPose, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 20.dp, end = 20.dp, top = 16.dp, bottom = 18.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "hmd // android v${BuildConfig.VERSION_NAME}",
                    color = HmdColors.OnFrame,
                    fontSize = 12.sp,
                    fontFamily = JBMono,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                StatusPill(
                    label = if (hasNotifPermission) "ONLINE" else "PERM REQ",
                    color = if (hasNotifPermission) HmdColors.Signal else HmdColors.Warn
                )
            }
            Text(
                text = "HOW'S MY\nDOWNLOAD?",
                color = HmdColors.Fg,
                fontSize = 62.sp,
                fontFamily = Shoulders,
                fontWeight = FontWeight.Black,
                letterSpacing = 0.005.em,
                style = TightDisplay.copy(lineHeight = 53.3.sp)
            )
        }
        Sammy(
            pose = pose,
            size = 84.dp,
            contentDescription = "Sammy",
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 22.dp)
                .offset(y = 4.dp)
        )
    }
}

/** Big 6-character code input: 56 dp, 22 sp bold, wide tracking, purple focus ring. */
@Composable
private fun PairingCodeField(value: String, onValueChange: (String) -> Unit) {
    val interaction = remember { MutableInteractionSource() }
    val focused by interaction.collectIsFocusedAsState()
    BasicTextField(
        value = value,
        onValueChange = onValueChange,
        singleLine = true,
        interactionSource = interaction,
        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters),
        cursorBrush = SolidColor(HmdColors.Signal),
        textStyle = TextStyle(
            color = HmdColors.Fg,
            fontFamily = JBMono,
            fontWeight = FontWeight.Bold,
            fontSize = 22.sp,
            letterSpacing = 0.42.em,
            textAlign = TextAlign.Center
        ),
        modifier = Modifier
            .fillMaxWidth()
            .then(
                if (focused) Modifier.border(3.dp, Color(0xFF2A1640), RoundedCornerShape(HmdShape.Radius + 3.dp)).padding(3.dp)
                else Modifier.padding(3.dp)
            )
            .height(56.dp)
            .background(HmdColors.Bg, RoundedCornerShape(HmdShape.Radius))
            .border(1.dp, if (focused) HmdColors.Flag else HmdColors.LineStrong, RoundedCornerShape(HmdShape.Radius)),
        decorationBox = { inner ->
            Box(Modifier.fillMaxSize().padding(start = 9.dp), contentAlignment = Alignment.Center) {
                if (value.isEmpty()) {
                    Text(
                        text = "5VQ4TT",
                        color = Color(0xFF4A4A57),
                        fontFamily = JBMono,
                        fontWeight = FontWeight.Bold,
                        fontSize = 22.sp,
                        letterSpacing = 0.42.em
                    )
                }
                inner()
            }
        }
    )
}

/** In-app "unpaired from <pc>" toast: rises in, hard purple shadow, Sammy waving. */
@Composable
private fun UnpairedToast(pcName: String, modifier: Modifier = Modifier) {
    val still = rememberReducedMotion()
    val rise = remember { Animatable(if (still) 1f else 0f) }
    LaunchedEffect(Unit) {
        rise.animateTo(1f, tween(420, easing = CubicBezierEasing(0.34f, 1.56f, 0.64f, 1f)))
    }
    Row(
        modifier = modifier
            .offset { IntOffset(0, ((1f - rise.value) * 16.dp.toPx()).toInt()) }
            .alpha(rise.value.coerceIn(0f, 1f))
            .hardShadow()
            .background(HmdColors.Raised, RoundedCornerShape(HmdShape.Radius))
            .border(1.dp, HmdColors.LineStrong, RoundedCornerShape(HmdShape.Radius))
            .padding(start = 8.dp, end = 16.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Sammy(SammyPose.Wave, 35.dp)
        Text(
            text = buildAnnotatedString {
                append("unpaired from ")
                withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(pcName) }
            },
            color = HmdColors.Fg,
            fontSize = 13.sp,
            fontFamily = JBMono,
            maxLines = 1
        )
    }
}

@Composable
fun DownloadItemCard(
    dl: AppDownloadItem,
    shownState: String = dl.state.lowercase(),
    pending: PendingCommand? = null,
    failure: String? = null,
    onCommand: (DownloadCommands.Action) -> Unit = {}
) {
    val totalKnown = dl.totalBytes != null && dl.totalBytes > 0
    val currentMB = String.format("%.1f", dl.bytesDownloaded / (1024.0 * 1024.0))
    val totalMB = if (totalKnown) String.format("%.1f", dl.totalBytes!! / (1024.0 * 1024.0)) else "?"
    val pctFloat = dl.percentage ?: if (totalKnown) ((dl.bytesDownloaded.toFloat() / dl.totalBytes!!) * 100f) else null
    val pctProgress = (pctFloat ?: 0f) / 100f

    val (label, badge, tone) = when (shownState) {
        "starting" -> Triple("Starting", Badges.Starting, HmdColors.Flag)
        "downloading" -> Triple("Downloading", Badges.Downloading, HmdColors.Signal)
        "paused" -> Triple("Paused", Badges.Paused, HmdColors.Warn)
        "completed" -> Triple("Complete", Badges.Completed, HmdColors.Signal)
        "failed" -> Triple("Failed", Badges.Failed, HmdColors.Fail)
        "offline" -> Triple("PC offline", Badges.Offline, HmdColors.Muted)
        else -> Triple(shownState, Badges.Offline, HmdColors.Muted)
    }
    val fill: Brush = when (shownState) {
        "paused" -> Brush.horizontalGradient(listOf(Color(0xFF6B5310), HmdColors.Warn))
        "failed" -> SolidColor(Color(0xFF7A2A2A))
        "offline" -> SolidColor(HmdColors.LineStrong)
        else -> HmdColors.Progress
    }
    val sizeLine = buildString {
        append("$currentMB / $totalMB MB")
        when (shownState) {
            "downloading", "starting" -> append(" · ${formatSpeed(dl.speedBytesSec)}")
            "offline" -> append(" · stalled")
        }
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(HmdColors.Raised, RoundedCornerShape(HmdShape.Radius))
            .border(1.dp, HmdColors.Line, RoundedCornerShape(HmdShape.Radius))
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = dl.filename,
                color = HmdColors.Fg,
                fontWeight = FontWeight.Bold,
                fontSize = 15.sp,
                fontFamily = JBMono,
                modifier = Modifier.weight(1f),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Badge(label, badge)
        }

        ProgressTrack(
            progress = if (pctFloat != null) pctProgress.coerceIn(0f, 1f) else null,
            pose = poseFor(shownState),
            fill = fill,
            alt = "Sammy: ${label.lowercase()}"
        )

        // Stats row
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.Bottom
        ) {
            Text(
                text = sizeLine,
                color = HmdColors.Muted,
                fontSize = 12.sp,
                fontFamily = JBMono,
                modifier = Modifier.weight(1f)
            )
            Text(
                text = if (pctFloat != null) "${String.format("%.1f", pctFloat)}%" else "LIVE",
                color = tone,
                fontSize = 14.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = JBMono
            )
        }

        // Pause / Resume / Restart, or what's in flight
        val actions = DownloadCommands.availableActions(dl.state, dl.canResume)
        if (pending != null) {
            // Without any answer the server reports expiry first; this is the last resort
            LaunchedEffect(pending) {
                val elapsed = System.currentTimeMillis() - pending.sentAt
                delay((DownloadRepository.PENDING_TIMEOUT_MS - elapsed).coerceAtLeast(0L))
                DownloadRepository.expirePending()
            }
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 48.dp)
                    .dashedBorder(HmdColors.LineStrong),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally)
            ) {
                CircularProgressIndicator(
                    color = HmdColors.Warn,
                    strokeWidth = 1.5.dp,
                    modifier = Modifier.size(12.dp)
                )
                Text(
                    text = "// " + (DownloadCommands.Action.fromWire(pending.action)?.pendingLabel ?: "Sending…").lowercase(),
                    color = HmdColors.Warn,
                    fontSize = 12.sp,
                    fontFamily = JBMono
                )
            }
        } else if (actions.isNotEmpty()) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                actions.forEach { action ->
                    val color = when (action) {
                        DownloadCommands.Action.PAUSE -> HmdColors.Warn
                        DownloadCommands.Action.RESUME -> HmdColors.Signal
                        DownloadCommands.Action.RESTART -> HmdColors.Flag
                    }
                    TerminalButton(
                        text = action.wire,
                        onClick = { onCommand(action) },
                        tone = color,
                        textColor = color,
                        modifier = Modifier.weight(1f)
                    )
                }
            }
        } else if (shownState == "completed") {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 48.dp)
                    .dashedBorder(HmdColors.LineStrong),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "// landed. go back to the desk.",
                    color = HmdColors.Muted,
                    fontSize = 12.sp,
                    fontFamily = JBMono
                )
            }
        }

        if (failure != null) {
            Text(
                text = "// error: $failure",
                color = HmdColors.Fail,
                fontSize = 12.sp,
                fontFamily = JBMono
            )
        }
    }
}

/**
 * 54 dp track zone: a 10 dp bar with Sammy standing on it at [progress] (0..1), kept inside
 * the bar. A null progress (size unknown) sweeps a block along the bar with Sammy at the start.
 */
@Composable
private fun ProgressTrack(progress: Float?, pose: SammyPose, fill: Brush, alt: String) {
    val still = rememberReducedMotion()
    val shown by animateFloatAsState(
        targetValue = progress ?: 0f,
        animationSpec = if (still) snap() else tween(400, easing = LinearEasing),
        label = "progress"
    )
    BoxWithConstraints(
        modifier = Modifier
            .fillMaxWidth()
            .height(54.dp)
    ) {
        val sammySize = 42.dp
        val trackWidth = maxWidth
        Sammy(
            pose = pose,
            size = sammySize,
            contentDescription = alt,
            modifier = Modifier
                .align(Alignment.BottomStart)
                .offset(x = (maxWidth - sammySize) * shown, y = (-9).dp)
        )
        Box(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .fillMaxWidth()
                .height(10.dp)
                .clip(RoundedCornerShape(HmdShape.RadiusSm))
                .background(HmdColors.Bg)
                .border(1.dp, HmdColors.Line, RoundedCornerShape(HmdShape.RadiusSm))
        ) {
            if (progress != null) {
                Box(
                    Modifier
                        .fillMaxHeight()
                        .fillMaxWidth(shown)
                        .background(fill)
                )
            } else if (still) {
                Box(Modifier.fillMaxSize().background(fill))
            } else {
                val sweep by rememberInfiniteTransition(label = "sweep").animateFloat(
                    initialValue = -0.3f, targetValue = 1f,
                    animationSpec = infiniteRepeatable(tween(1400, easing = LinearEasing)),
                    label = "sweepX"
                )
                Box(
                    Modifier
                        .fillMaxHeight()
                        .fillMaxWidth(0.3f)
                        .offset(x = trackWidth * sweep)
                        .background(fill)
                )
            }
        }
    }
}
