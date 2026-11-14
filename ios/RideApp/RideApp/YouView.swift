import SwiftUI

/// Tallies, streaks and personal bests (GET /v1/you), in the D look. Counts visible rides only;
/// the text comes from the server's rules (rideengine/analysis/records.py), not an AI model.
struct YouView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        if let since = model.you?.since.flatMap(Self.month) { MonoLabel("On record since \(since)") }
                        Text("You").font(Theme.heading(44)).foregroundStyle(Theme.ink)
                    }
                    .padding(.horizontal, 4)
                    .padding(.top, 8)

                    if let you = model.you, you.all.rides > 0 {
                        AllTimeHero(tally: you.all)
                        TotalsPanel(you: you)
                        YearCompare(you: you)
                        BestsList(bests: you.bests, rides: model.rides)
                        LatelyList(recent: you.recent.filter { !$0.notes.isEmpty }, rides: model.rides)
                    } else if let error = model.error {
                        Text(error).font(Theme.text(13)).foregroundStyle(Theme.heart)
                    } else if !model.isLoading {
                        Text("Your totals and personal bests show up here once rides arrive.")
                            .font(Theme.text(15)).foregroundStyle(Theme.inkMuted)
                            .padding(.vertical, 24)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 24)
            }
            .background(Theme.ground.ignoresSafeArea())
            .toolbar(.hidden, for: .navigationBar)
            .refreshable { await model.refresh() }
        }
    }

    /// "2025-03-29" → "March 2025"
    static func month(_ iso: String) -> String? {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: iso)?.formatted(.dateTime.month(.wide).year())
    }
}

/// Cobalt hero: every kilometre on record, and what that distance would get you.
private struct AllTimeHero: View {
    let tally: YouSummary.Tally

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            MonoLabel("All time", color: Theme.cobaltSoft)
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(Format.hero(tally.km, decimals: 0)).font(Theme.hero(64)).lineLimit(1).minimumScaleFactor(0.6)
                Text("km").font(Theme.text(16)).foregroundStyle(Theme.cobaltSoft)
            }
            if let crow = tally.crowFlies {
                Text("About \(crow), as the crow flies.")
                    .font(Theme.text(14)).foregroundStyle(Color(hex: 0xE3E8F7))
            }
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 20).padding(.vertical, 18)
        .background(Theme.cobalt, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}

/// Dark panel: rides, hours, climbing (in Everests too) and the longest streak.
private struct TotalsPanel: View {
    let you: YouSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            LazyVGrid(columns: [GridItem(.flexible(), alignment: .leading), GridItem(.flexible(), alignment: .leading)],
                      alignment: .leading, spacing: 14) {
                HeroStat(label: "Rides", value: "\(you.all.rides)", unit: nil)
                HeroStat(label: "In the saddle", value: Format.hero(you.all.hours, decimals: 0), unit: "h")
                HeroStat(label: "Climbed", value: Format.hero(you.all.ascentM, decimals: 0), unit: "m")
                HeroStat(label: "Longest streak", value: "\(you.streak.longestWeeks)", unit: "weeks")
            }
            Rectangle().fill(Theme.panelLine).frame(height: 1)
            Text(everestLine).font(Theme.text(14)).foregroundStyle(Theme.panelLabel)
                .fixedSize(horizontal: false, vertical: true)
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 18).padding(.vertical, 16)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    private var everestLine: String {
        var line = "\(Format.number(you.all.everests, decimals: 2)) Everests of climbing."
        let now = you.streak.currentWeeks
        line += now > 0 ? " \(now) week\(now == 1 ? "" : "s") in a row right now." : " Your next ride starts a new streak."
        return line
    }
}

/// This year against last year to the same day, as two bars.
private struct YearCompare: View {
    let you: YouSummary

    var body: some View {
        let now = you.year, then = you.lastYearToDate
        let top = max(now.km, then.km, 1)
        VStack(alignment: .leading, spacing: 12) {
            MonoLabel("This year so far")
            bar(label: now.label ?? "", km: now.km, share: now.km / top, color: Theme.cobalt)
            bar(label: then.label ?? "", km: then.km, share: then.km / top, color: Theme.inkMuted.opacity(0.45))
            Text(summary(now: now.km, then: then.km))
                .font(Theme.text(14)).foregroundStyle(Theme.inkSoft)
                .fixedSize(horizontal: false, vertical: true)
            if let big = you.biggestMonth {
                Text("Biggest month: \(big.label ?? ""), \(Format.number(big.km, decimals: 0)) km over \(big.rides) rides.")
                    .font(Theme.text(14)).foregroundStyle(Theme.inkSoft)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16).surfaceCard()
    }

    private func bar(label: String, km: Double, share: Double, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(label).font(Theme.mono(12)).foregroundStyle(Theme.inkMuted)
                Spacer()
                Text("\(Format.number(km, decimals: 0)) km").font(Theme.text(15, .semibold)).monospacedDigit()
            }
            GeometryReader { geo in
                Capsule().fill(color).frame(width: max(6, geo.size.width * share))
            }
            .frame(height: 10)
        }
        .accessibilityElement(children: .combine)
    }

    private func summary(now: Double, then: Double) -> String {
        let diff = now - then
        if then == 0 { return "\(Format.number(now, decimals: 0)) km so far this year." }
        if abs(diff) < 1 { return "Level with last year." }
        return "\(Format.number(abs(diff), decimals: 0)) km \(diff > 0 ? "ahead of" : "behind") last year at this point."
    }
}

/// Personal bests; each opens its ride.
private struct BestsList: View {
    let bests: [YouSummary.Best]
    let rides: [RideSummary]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            MonoLabel("Personal bests").padding(.horizontal, 4).padding(.top, 8)
            ForEach(bests) { best in
                if let ride = rides.first(where: { $0.rideId == best.rideId }) {
                    NavigationLink { RideDetailView(ride: ride) } label: { row(best) }.buttonStyle(.plain)
                } else {
                    row(best)
                }
            }
        }
    }

    private func row(_ best: YouSummary.Best) -> some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                MonoLabel(best.label)
                Text(Date(timeIntervalSince1970: best.start).formatted(.dateTime.day().month(.wide).year()))
                    .font(Theme.text(14)).foregroundStyle(Theme.inkMuted)
            }
            Spacer(minLength: 8)
            Text(best.text).font(Theme.text(22, .semibold)).monospacedDigit().foregroundStyle(Theme.ink)
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
        .surfaceCard(radius: 16)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }
}

/// The latest rides that had something worth saying.
private struct LatelyList: View {
    let recent: [YouSummary.Recent]
    let rides: [RideSummary]

    var body: some View {
        if !recent.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                MonoLabel("Lately").padding(.horizontal, 4).padding(.top, 8)
                ForEach(recent) { r in
                    if let ride = rides.first(where: { $0.rideId == r.rideId }) {
                        NavigationLink { RideDetailView(ride: ride) } label: { row(r) }.buttonStyle(.plain)
                    } else {
                        row(r)
                    }
                }
            }
        }
    }

    private func row(_ r: YouSummary.Recent) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("\(Date(timeIntervalSince1970: r.start).formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated))) · \(Format.number(r.km, decimals: 1)) km")
                .font(Theme.mono(12)).foregroundStyle(Theme.inkMuted)
            NoteList(notes: r.notes)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 16).padding(.vertical, 12)
        .surfaceCard(radius: 16)
        .contentShape(Rectangle())
    }
}

/// A ride's notes: personal bests marked with a cobalt star, the rest as plain lines.
struct NoteList: View {
    let notes: [RideNote]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(notes, id: \.self) { note in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Image(systemName: note.pb ? "star.fill" : "circle.fill")
                        .font(.system(size: note.pb ? 11 : 5))
                        .foregroundStyle(note.pb ? Theme.cobalt : Theme.inkMuted)
                        .frame(width: 12)
                    (Text(note.text).font(Theme.text(15, note.pb ? .semibold : .regular)).foregroundColor(Theme.ink)
                     + Text(note.detail.map { "  \($0)" } ?? "").font(Theme.mono(12)).foregroundColor(Theme.inkMuted))
                        .fixedSize(horizontal: false, vertical: true)
                }
                .accessibilityElement(children: .combine)
            }
        }
    }
}
