package com.notifs.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val DarkColorScheme = darkColorScheme(
    primary = PurpleBrand,
    onPrimary = TextWhite,
    primaryContainer = BgElevated,
    onPrimaryContainer = PurpleLight,
    secondary = GreenNeon,
    onSecondary = BgCanvas,
    background = BgCanvas,
    onBackground = TextWhite,
    surface = BgCard,
    onSurface = TextWhite,
    surfaceVariant = BgElevated,
    onSurfaceVariant = TextDim,
    outline = BorderSubtle
)

@Composable
fun DownloadNotifsTheme(
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        content = content
    )
}
