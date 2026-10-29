package com.notifs.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.text.TextStyle

private val DarkColorScheme = darkColorScheme(
    primary = HmdColors.Frame,
    onPrimary = HmdColors.Fg,
    primaryContainer = HmdColors.Raised,
    onPrimaryContainer = HmdColors.Flag,
    secondary = HmdColors.Signal,
    onSecondary = HmdColors.Bg,
    background = HmdColors.Bg,
    onBackground = HmdColors.Fg,
    surface = HmdColors.Surface,
    onSurface = HmdColors.Fg,
    surfaceVariant = HmdColors.Raised,
    onSurfaceVariant = HmdColors.Muted,
    outline = HmdColors.LineStrong
)

// JetBrains Mono everywhere Material draws its own text (dialogs, fields)
private val HmdTypography = Typography().run {
    fun TextStyle.mono() = copy(fontFamily = JBMono)
    copy(
        bodyLarge = bodyLarge.mono(), bodyMedium = bodyMedium.mono(), bodySmall = bodySmall.mono(),
        labelLarge = labelLarge.mono(), labelMedium = labelMedium.mono(), labelSmall = labelSmall.mono(),
        titleLarge = titleLarge.mono(), titleMedium = titleMedium.mono(), titleSmall = titleSmall.mono(),
        headlineSmall = headlineSmall.mono()
    )
}

@Composable
fun DownloadNotifsTheme(
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        typography = HmdTypography,
        content = content
    )
}
