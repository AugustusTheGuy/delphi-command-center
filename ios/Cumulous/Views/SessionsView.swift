import SwiftUI

/// CardSession “Sessions” tab — maps to Cumulous challenge / Confirm User auth model.
struct SessionsView: View {
    @ObservedObject private var api = CumulousAPI.shared
    @State private var status = ""

    var body: some View {
        NavigationStack {
            ZStack {
                CumulousTheme.bg.ignoresSafeArea()
                ScrollView {
                    VStack(spacing: 16) {
                        CumulousCard {
                            VStack(alignment: .leading, spacing: 10) {
                                Text("CardSessions")
                                    .font(.system(size: 22, weight: .semibold))
                                    .tracking(-0.4)
                                    .foregroundStyle(CumulousTheme.text)
                                Text("Time-limited, scoped access for backup and restore. Inspired by Apple CardSession HCE — in Cumulous, real auth uses live 4-digit codes + Apple Account 2FA.")
                                    .font(.system(size: 14))
                                    .foregroundStyle(CumulousTheme.muted)
                                SoftChip(text: "No long-lived secrets leave the device", ok: true)
                            }
                        }

                        CumulousCard {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("SESSION TYPES")
                                    .font(.system(size: 11, weight: .semibold))
                                    .foregroundStyle(CumulousTheme.faint)
                                sessionType(title: "Backup", detail: "Authorize photo + full system backup")
                                sessionType(title: "Restore / Confirm User", detail: "Unlock view & restore on Mac")
                                sessionType(title: "CEO Override", detail: "30-minute recovery code fanout")
                            }
                        }

                        NavigationLink {
                            ConfirmUserView()
                        } label: {
                            Label("Open Confirm User", systemImage: "person.badge.shield.checkmark")
                        }
                        .buttonStyle(PrimaryButtonStyle())

                        if !status.isEmpty {
                            Text(status)
                                .font(.footnote)
                                .foregroundStyle(CumulousTheme.muted)
                        }

                        CumulousCard {
                            VStack(alignment: .leading, spacing: 6) {
                                Text("HOW IT WORKS")
                                    .font(.system(size: 11, weight: .semibold))
                                    .foregroundStyle(CumulousTheme.faint)
                                Text("1. Mac requests a challenge\n2. Code is pushed to your Apple devices\n3. You enter it only on Mac (never shown in entry UI)\n4. 2FA confirms the Apple Account\n5. Backup or restore proceeds")
                                    .font(.system(size: 14))
                                    .foregroundStyle(CumulousTheme.text)
                            }
                        }
                    }
                    .padding(20)
                }
            }
            .navigationTitle("Sessions")
            .navigationBarTitleDisplayMode(.large)
            .task { _ = await api.ping() }
            .preferredColorScheme(.dark)
        }
    }

    private func sessionType(title: String, detail: String) -> some View {
        HStack(alignment: .top) {
            Circle()
                .fill(CumulousTheme.accent.opacity(0.35))
                .frame(width: 8, height: 8)
                .padding(.top, 6)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(CumulousTheme.text)
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(CumulousTheme.muted)
            }
            Spacer()
        }
        .padding(.vertical, 4)
    }
}
