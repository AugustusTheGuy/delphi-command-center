import SwiftUI

/// Cumulous design system — matte black · thin metallic silver · Apple blue actions.
/// Keep aligned with `cumulous/theme.py` on Mac.
enum CumulousTheme {
    /// Matte black background
    static let bg = Color(red: 0.02, green: 0.02, blue: 0.02) // #050505
    static let elevated = Color(red: 0.039, green: 0.039, blue: 0.039) // #0a0a0a
    static let card = Color(red: 0.055, green: 0.055, blue: 0.055) // #0e0e0e
    static let cardGlass = Color.white.opacity(0.05)
    /// Thin metallic silver hairlines
    static let cardStroke = Color(red: 0.78, green: 0.79, blue: 0.82).opacity(0.28)
    static let silver = Color(red: 0.784, green: 0.792, blue: 0.824) // #c8cad2
    /// Text: silver → bright white glow
    static let muted = Color(red: 0.78, green: 0.78, blue: 0.80)
    static let faint = Color(red: 0.557, green: 0.557, blue: 0.576)
    static let text = Color.white
    /// Apple systemBlue #007AFF — additive action buttons
    static let accent = Color(red: 0.0, green: 0.478, blue: 1.0)
    /// Apple HIG traffic-light green for affirmed status (not action buttons)
    static let statusGreen = Color(red: 0.204, green: 0.780, blue: 0.349) // #34C759
    static let statusGreenBright = Color(red: 0.188, green: 0.820, blue: 0.345) // #30D158
    static let success = statusGreen
    /// Backup / restore action fills (same Apple blue)
    static let backupGreen = accent
    static let restoreSkyBlue = accent
    static let amber = Color(red: 1.0, green: 0.84, blue: 0.04)
    static let attention = amber
    /// In-tab red action buttons (not traffic-light chrome)
    static let danger = Color(red: 1.0, green: 0.231, blue: 0.188) // #FF3B30
    /// Status unaffirmed red (Apple systemRed)
    static let statusRed = Color(red: 1.0, green: 0.231, blue: 0.188) // #FF3B30
    /// Traffic-light close stays full size (14pt)
    static let trafficCloseSize: CGFloat = 14
    /// In-tab red controls are 15% smaller than default action padding
    static let inAppRedScale: CGFloat = 0.85

    static let radiusCard: CGFloat = 20
    static let radiusButton: CGFloat = 14
    static let radiusPill: CGFloat = 999
    static let spacing: CGFloat = 14
}

// MARK: - Glassy button backgrounds (View overlays, not ShapeStyle)

private struct GlassBlueBackground: View {
    var pressed: Bool
    var cornerRadius: CGFloat

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(
                LinearGradient(
                    colors: [
                        Color(red: 0.1, green: 0.56, blue: 1.0),
                        CumulousTheme.accent,
                        Color(red: 0.0, green: 0.38, blue: 0.8),
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [
                                Color.white.opacity(pressed ? 0.22 : 0.42),
                                Color.white.opacity(0.08),
                                Color.clear,
                            ],
                            startPoint: .top,
                            endPoint: UnitPoint(x: 0.5, y: 0.55)
                        )
                    )
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(Color.white.opacity(0.28), lineWidth: 1)
            )
            .shadow(color: CumulousTheme.accent.opacity(0.32), radius: 8, y: 3)
            .opacity(pressed ? 0.88 : 1)
    }
}

private struct GlassRedBackground: View {
    var pressed: Bool
    var cornerRadius: CGFloat

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(
                LinearGradient(
                    colors: [
                        Color(red: 1.0, green: 0.42, blue: 0.39),
                        CumulousTheme.danger,
                        Color(red: 0.84, green: 0.0, blue: 0.08),
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [
                                Color.white.opacity(pressed ? 0.2 : 0.38),
                                Color.white.opacity(0.08),
                                Color.clear,
                            ],
                            startPoint: .top,
                            endPoint: UnitPoint(x: 0.5, y: 0.55)
                        )
                    )
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(Color.white.opacity(0.26), lineWidth: 1)
            )
            .shadow(color: CumulousTheme.danger.opacity(0.3), radius: 7, y: 2)
            .opacity(pressed ? 0.88 : 1)
    }
}

struct CumulousCard<Content: View>: View {
    var padding: CGFloat = 16
    @ViewBuilder var content: () -> Content
    var body: some View {
        content()
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: CumulousTheme.radiusCard, style: .continuous)
                    .fill(CumulousTheme.card)
            )
            .overlay(
                RoundedRectangle(cornerRadius: CumulousTheme.radiusCard, style: .continuous)
                    .stroke(CumulousTheme.cardStroke, lineWidth: 1)
            )
    }
}

struct PrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 16, weight: .semibold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14)
            .background(
                GlassBlueBackground(
                    pressed: configuration.isPressed,
                    cornerRadius: CumulousTheme.radiusButton
                )
            )
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

/// Positive / additive actions (backup) — glassy Apple blue
struct BackupGreenButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 14, weight: .semibold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 13)
            .background(
                GlassBlueBackground(
                    pressed: configuration.isPressed,
                    cornerRadius: CumulousTheme.radiusButton
                )
            )
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

/// Additive restore — same glassy Apple blue
struct RestoreSkyBlueButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 14, weight: .semibold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 13)
            .background(
                GlassBlueBackground(
                    pressed: configuration.isPressed,
                    cornerRadius: CumulousTheme.radiusButton
                )
            )
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

/// In-tab red actions only — glassy + 15% smaller. Not for traffic-light dots.
struct DenyRedButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        let r = CumulousTheme.radiusButton * CumulousTheme.inAppRedScale
        return configuration.label
            .font(.system(size: 14 * CumulousTheme.inAppRedScale, weight: .semibold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 13 * CumulousTheme.inAppRedScale)
            .background(
                GlassRedBackground(pressed: configuration.isPressed, cornerRadius: r)
            )
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

struct SecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 16, weight: .semibold))
            .foregroundStyle(CumulousTheme.text)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14)
            .background(
                RoundedRectangle(cornerRadius: CumulousTheme.radiusButton, style: .continuous)
                    .fill(Color.white.opacity(configuration.isPressed ? 0.06 : 0.09))
            )
            .overlay(
                RoundedRectangle(cornerRadius: CumulousTheme.radiusButton, style: .continuous)
                    .stroke(CumulousTheme.cardStroke, lineWidth: 1)
            )
    }
}

struct SoftChip: View {
    let text: String
    var ok: Bool = false
    /// When true, uses Live (green 8× pulse @ 1.25s) / No Connection (red 3× pulse @ 1.5s)
    var liveConnection: Bool = false
    @State private var pulse = false

    var body: some View {
        Text(text)
            .font(.system(size: 11, weight: .semibold))
            .foregroundStyle(foreground)
            .shadow(color: textGlow, radius: pulse ? textGlowRadius : textGlowRadius * 0.45)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(Capsule().fill(fill))
            .overlay(Capsule().stroke(stroke, lineWidth: 1))
            .shadow(color: boxGlow, radius: pulse ? boxGlowRadius : boxGlowRadius * 0.4)
            .onAppear {
                guard liveConnection else { return }
                withAnimation(
                    .easeInOut(duration: ok ? 1.25 : 1.5)
                    .repeatForever(autoreverses: true)
                ) {
                    pulse = true
                }
            }
    }

    private var foreground: Color {
        if liveConnection { return ok ? CumulousTheme.statusGreenBright : CumulousTheme.statusRed }
        return ok ? CumulousTheme.accent : CumulousTheme.muted
    }

    private var stroke: Color {
        if liveConnection {
            return ok ? CumulousTheme.statusGreenBright.opacity(0.65) : CumulousTheme.statusRed.opacity(0.55)
        }
        return ok ? CumulousTheme.accent.opacity(0.35) : CumulousTheme.cardStroke
    }

    private var fill: Color {
        if liveConnection {
            return ok ? CumulousTheme.statusGreen.opacity(0.12) : Color(red: 0.31, green: 0, blue: 0.03).opacity(0.45)
        }
        return Color.white.opacity(0.05)
    }

    private var textGlow: Color {
        guard liveConnection else { return .clear }
        // Live 8× / No Connection 3× relative to a soft base glow
        return ok
            ? CumulousTheme.statusGreenBright.opacity(pulse ? 0.95 : 0.45)
            : CumulousTheme.statusRed.opacity(pulse ? 0.7 : 0.35)
    }

    private var textGlowRadius: CGFloat { ok ? 16 : 10 }

    private var boxGlow: Color {
        guard liveConnection else { return .clear }
        return ok
            ? CumulousTheme.statusGreenBright.opacity(pulse ? 0.85 : 0.35)
            : Color(red: 0.5, green: 0, blue: 0.05).opacity(pulse ? 0.55 : 0.25)
    }

    private var boxGlowRadius: CGFloat { ok ? 22 : 14 }
}

/// Home Status metric tile: "Storage:" + value with steady green/red glow.
struct StatusMetricTile: View {
    let label: String  // include trailing colon, e.g. "Storage:"
    let value: String
    var affirmed: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(CumulousTheme.faint)
            Text(value)
                .font(.system(size: 16, weight: .semibold))
                .tracking(-0.3)
                .foregroundStyle(affirmed ? CumulousTheme.statusGreen : CumulousTheme.statusRed)
                .shadow(
                    color: (affirmed ? CumulousTheme.statusGreenBright : CumulousTheme.statusRed)
                        .opacity(affirmed ? 0.9 : 0.55),
                    radius: affirmed ? 14 : 8
                )
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(CumulousTheme.card)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(
                    (affirmed ? CumulousTheme.statusGreen : CumulousTheme.statusRed).opacity(affirmed ? 0.55 : 0.45),
                    lineWidth: 1
                )
        )
        .shadow(
            color: (affirmed ? CumulousTheme.statusGreenBright : Color(red: 0.45, green: 0, blue: 0.04))
                .opacity(affirmed ? 0.55 : 0.35),
            radius: affirmed ? 16 : 10
        )
    }
}
