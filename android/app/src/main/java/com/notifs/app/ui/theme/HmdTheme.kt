// How's My Download: design tokens for Jetpack Compose (from docs/design/tokens/HmdTheme.kt).
// Fonts: res/font/shoulders_900.ttf and jetbrains_mono_{regular,bold}.ttf, converted from the
// handoff's woff2 files (JetBrains Mono is variable there; static 400/700 instances work on API 26).
// Sprite sheet: res/drawable-nodpi/sammy.png.
package com.notifs.app.ui.theme

import android.provider.Settings
import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.imageResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import com.notifs.app.R

object HmdColors {
    val Frame = Color(0xFF8A05FF)
    val FrameDeep = Color(0xFF6F00D6)
    val Bg = Color(0xFF09090C)
    val Surface = Color(0xFF111116)
    val Raised = Color(0xFF181820)
    val Line = Color(0xFF23232C)
    val LineStrong = Color(0xFF32323F)
    val Fg = Color(0xFFFFFFFF)
    val Muted = Color(0xFFA1A1AA)
    val Faint = Color(0xFF8E8E98)
    val Flag = Color(0xFFC084FC)
    val Signal = Color(0xFF61CF92)
    val SignalDeepBg = Color(0xFF14261C)
    val SignalDeepBorder = Color(0xFF2F6B4A)
    val Warn = Color(0xFFFBBF24)
    val Fail = Color(0xFFF87171)
    val OnFrame = Color(0xFFECDCFF)
    val Progress = Brush.horizontalGradient(listOf(Frame, Signal))
}

object HmdShape {
    val Radius = 4.dp
    val RadiusSm = 2.dp
}

val Shoulders = FontFamily(Font(R.font.shoulders_900, FontWeight.Black))
val JBMono = FontFamily(
    Font(R.font.jetbrains_mono_regular, FontWeight.Normal),
    Font(R.font.jetbrains_mono_bold, FontWeight.Bold)
)

/** Sprite rows in sammy.png (4 frames x 28 px per row). */
enum class SammyPose(val row: Int, val fps: Float) {
    Starting(0, 3f), Downloading(1, 8f), Paused(2, 2f), Completed(3, 5f), Failed(4, 2f), Offline(5, 1.5f),
    Deliver(6, 10f), Wave(7, 5f), Key(8, 3f), Think(9, 2.5f), Chill(10, 2f),
    CarryPhone(11, 4f), CarryExt(12, 4f), CarryQr(13, 4f), Laptop(14, 6f)
}

/** True when the system "remove animations" setting is on (animator duration scale 0). */
@Composable
fun rememberReducedMotion(): Boolean {
    val resolver = LocalContext.current.contentResolver
    return remember(resolver) {
        Settings.Global.getFloat(resolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
    }
}

/** Pixel-sharp animated Sammy. size = 28.dp * scale (e.g. 42.dp on progress bars, 84.dp in the header). */
@Composable
fun Sammy(pose: SammyPose, sheet: ImageBitmap, size: Dp, modifier: Modifier = Modifier, animate: Boolean = true) {
    val frame by if (animate) {
        rememberInfiniteTransition(label = "sammy").animateValue(
            initialValue = 0, targetValue = 4, typeConverter = Int.VectorConverter,
            animationSpec = infiniteRepeatable(tween((4000 / pose.fps).toInt(), easing = LinearEasing)),
            label = "frame"
        )
    } else remember { mutableIntStateOf(0) }
    Canvas(modifier.size(size)) {
        drawImage(
            image = sheet,
            srcOffset = IntOffset(frame.coerceIn(0, 3) * 28, pose.row * 28),
            srcSize = IntSize(28, 28),
            dstSize = IntSize(this.size.width.toInt(), this.size.height.toInt()),
            filterQuality = FilterQuality.None
        )
    }
}

/** [Sammy] with the bundled sheet; stands still when reduced motion is on. */
@Composable
fun Sammy(pose: SammyPose, size: Dp, modifier: Modifier = Modifier, contentDescription: String? = null) {
    val sheet = ImageBitmap.imageResource(R.drawable.sammy)
    val described = if (contentDescription != null) {
        modifier.semantics { this.contentDescription = contentDescription }
    } else modifier
    Sammy(pose, sheet, size, described, animate = !rememberReducedMotion())
}
