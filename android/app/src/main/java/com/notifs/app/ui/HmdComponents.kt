package com.notifs.app.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.notifs.app.R
import com.notifs.app.ui.theme.HmdColors
import com.notifs.app.ui.theme.HmdShape
import com.notifs.app.ui.theme.JBMono
import com.notifs.app.ui.theme.rememberReducedMotion

private val Spring = CubicBezierEasing(0.34f, 1.56f, 0.64f, 1f)

/** Section card: surface, 1 dp border, 4 dp radius, 16 dp padding. */
@Composable
fun SectionCard(
    modifier: Modifier = Modifier,
    border: Color = HmdColors.Line,
    gap: Dp = 12.dp,
    content: @Composable ColumnScope.() -> Unit
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .background(HmdColors.Surface, RoundedCornerShape(HmdShape.Radius))
            .border(1.dp, border, RoundedCornerShape(HmdShape.Radius))
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(gap),
        content = content
    )
}

/** `--name [ sub_label ]` in flag purple with a faint suffix. */
@Composable
fun SectionLabel(name: String, sub: String, modifier: Modifier = Modifier) {
    Text(
        text = buildAnnotatedString {
            append(name)
            append(" ")
            withStyle(SpanStyle(color = HmdColors.Faint, fontWeight = FontWeight.Normal)) { append(sub) }
        },
        color = HmdColors.Flag,
        fontFamily = JBMono,
        fontWeight = FontWeight.Bold,
        fontSize = 13.sp,
        modifier = modifier
    )
}

data class BadgeStyle(val fg: Color, val bg: Color, val border: Color)

object Badges {
    val Starting = BadgeStyle(HmdColors.Flag, Color(0xFF1F1230), Color(0xFF4B2A73))
    val Downloading = BadgeStyle(HmdColors.Signal, HmdColors.SignalDeepBg, HmdColors.SignalDeepBorder)
    val Paused = BadgeStyle(HmdColors.Warn, Color(0xFF2A2108), Color(0xFF6B5310))
    val Completed = BadgeStyle(HmdColors.Bg, HmdColors.Signal, HmdColors.Signal)
    val Failed = BadgeStyle(HmdColors.Fail, Color(0xFF2A1010), Color(0xFF6B2525))
    val Offline = BadgeStyle(HmdColors.Muted, HmdColors.Raised, HmdColors.LineStrong)
}

@Composable
fun Badge(label: String, style: BadgeStyle, modifier: Modifier = Modifier) {
    Text(
        text = label.uppercase(),
        color = style.fg,
        fontFamily = JBMono,
        fontWeight = FontWeight.Bold,
        fontSize = 10.5.sp,
        letterSpacing = 0.08.em,
        maxLines = 1,
        modifier = modifier
            .background(style.bg, RoundedCornerShape(HmdShape.RadiusSm))
            .border(1.dp, style.border, RoundedCornerShape(HmdShape.RadiusSm))
            .padding(horizontal = 8.dp, vertical = 6.dp)
    )
}

/** 6 dp square that blinks with steps(2) over 1.6 s. Takes [color]. */
@Composable
fun BlinkDot(color: Color, modifier: Modifier = Modifier, blink: Boolean = true) {
    val animate = blink && !rememberReducedMotion()
    val alpha = if (animate) {
        val phase by rememberInfiniteTransition(label = "dot").animateValue(
            initialValue = 0, targetValue = 2, typeConverter = Int.VectorConverter,
            animationSpec = infiniteRepeatable(tween(1600, easing = LinearEasing)),
            label = "dotPhase"
        )
        if (phase == 0) 1f else 0.25f
    } else 1f
    Box(
        modifier
            .size(6.dp)
            .alpha(alpha)
            .background(color)
    )
}

/** Status pill: bg background, coloured text and a blinking dot. */
@Composable
fun StatusPill(label: String, color: Color, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .background(HmdColors.Bg, RoundedCornerShape(HmdShape.RadiusSm))
            .padding(horizontal = 10.dp, vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(7.dp)
    ) {
        BlinkDot(color)
        Text(
            text = label,
            color = color,
            fontFamily = JBMono,
            fontWeight = FontWeight.Bold,
            fontSize = 11.sp,
            letterSpacing = 0.1.em,
            maxLines = 1
        )
    }
}

/**
 * Terminal button: surface fill, line-strong border, a prompt in [tone]. Pressing it takes
 * the tone on the border, slides the prompt right and nudges the button down 1 dp.
 */
@Composable
fun TerminalButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    tone: Color = HmdColors.Flag,
    textColor: Color = HmdColors.Fg,
    prompt: String = ">",
    enabled: Boolean = true,
    height: Dp = 48.dp,
    fontSize: Float = 14f,
    background: Color = HmdColors.Surface,
    content: (@Composable () -> Unit)? = null
) {
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val still = rememberReducedMotion()
    val nudge by animateDpAsState(
        if (pressed && !still) 1.dp else 0.dp, tween(80), label = "nudge"
    )
    val promptShift by animateDpAsState(
        if (pressed && !still) 4.dp else 0.dp,
        if (still) snap() else tween(350, easing = Spring), label = "prompt"
    )
    Row(
        modifier = modifier
            .offset { IntOffset(0, nudge.roundToPx()) }
            .heightIn(min = height)
            .alpha(if (enabled) 1f else 0.6f)
            .background(if (pressed) HmdColors.Raised else background, RoundedCornerShape(HmdShape.Radius))
            .border(1.dp, if (pressed) tone else HmdColors.LineStrong, RoundedCornerShape(HmdShape.Radius))
            .clickable(interactionSource = interaction, indication = null, enabled = enabled, role = Role.Button, onClick = onClick)
            .padding(horizontal = 14.dp),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (content != null) {
            content()
        } else {
            Text(
                text = prompt,
                color = tone,
                fontFamily = JBMono,
                fontWeight = FontWeight.Bold,
                fontSize = fontSize.sp,
                modifier = Modifier.offset { IntOffset(promptShift.roundToPx(), 0) }
            )
            Spacer(Modifier.width(10.dp))
            Text(
                text = text,
                color = textColor,
                fontFamily = JBMono,
                fontWeight = FontWeight.Bold,
                fontSize = fontSize.sp,
                maxLines = 1
            )
        }
    }
}

/** Green call-to-action with the pixel QR glyph, UPPERCASE ink text. */
@Composable
fun CtaButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, height: Dp = 56.dp) {
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val still = rememberReducedMotion()
    val nudge by animateDpAsState(if (pressed && !still) 1.dp else 0.dp, tween(80), label = "ctaNudge")
    Row(
        modifier = modifier
            .offset { IntOffset(0, nudge.roundToPx()) }
            .fillMaxWidth()
            .heightIn(min = height)
            .background(HmdColors.Signal, RoundedCornerShape(HmdShape.Radius))
            .clickable(interactionSource = interaction, indication = null, role = Role.Button, onClick = onClick),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            painter = painterResource(R.drawable.ic_qr_glyph),
            contentDescription = null,
            tint = HmdColors.Bg,
            modifier = Modifier.size(14.dp)
        )
        Spacer(Modifier.width(10.dp))
        Text(
            text = text.uppercase(),
            color = HmdColors.Bg,
            fontFamily = JBMono,
            fontWeight = FontWeight.Bold,
            fontSize = 14.sp,
            letterSpacing = 0.06.em
        )
    }
}

/** Square 54x32 toggle with a spring knob. On: signal border, signal-deep fill, signal knob. */
@Composable
fun HmdToggle(checked: Boolean, onCheckedChange: (Boolean) -> Unit, modifier: Modifier = Modifier) {
    val still = rememberReducedMotion()
    val knobX by animateDpAsState(
        if (checked) 22.dp else 0.dp,
        if (still) snap() else tween(360, easing = Spring), label = "knob"
    )
    val track by animateColorAsState(if (checked) HmdColors.SignalDeepBg else HmdColors.Raised, label = "track")
    val edge by animateColorAsState(if (checked) HmdColors.Signal else HmdColors.LineStrong, label = "edge")
    val knob by animateColorAsState(if (checked) HmdColors.Signal else HmdColors.Faint, label = "knobColor")
    Box(
        modifier = modifier
            .size(width = 54.dp, height = 32.dp)
            .background(track, RoundedCornerShape(HmdShape.Radius))
            .border(1.dp, edge, RoundedCornerShape(HmdShape.Radius))
            .toggleable(value = checked, role = Role.Switch, onValueChange = onCheckedChange)
    ) {
        Box(
            Modifier
                .padding(5.dp)
                .offset { IntOffset(knobX.roundToPx(), 0) }
                .size(20.dp)
                .background(knob, RoundedCornerShape(HmdShape.RadiusSm))
        )
    }
}

/** 1 dp dashed rounded border (empty states and card footers). */
fun Modifier.dashedBorder(color: Color, radius: Dp = HmdShape.Radius): Modifier = drawBehind {
    val stroke = 1.dp.toPx()
    drawRoundRect(
        color = color,
        topLeft = Offset(stroke / 2, stroke / 2),
        size = size.copy(width = size.width - stroke, height = size.height - stroke),
        cornerRadius = CornerRadius(radius.toPx()),
        style = Stroke(width = stroke, pathEffect = PathEffect.dashPathEffect(floatArrayOf(3.dp.toPx(), 3.dp.toPx())))
    )
}

/** Hard 4 dp drop shadow in frame-deep, drawn behind the element. */
fun Modifier.hardShadow(offset: Dp = 4.dp, color: Color = HmdColors.FrameDeep, radius: Dp = HmdShape.Radius): Modifier =
    drawBehind {
        val o = offset.toPx()
        drawRoundRect(color = color, topLeft = Offset(o, o), size = size, cornerRadius = CornerRadius(radius.toPx()))
    }
