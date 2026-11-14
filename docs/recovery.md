# Recovery and fitness from Apple Health

Agreed 14 Nov 2026: the app reads more from Apple Health, for recovery and fitness only.

## What's read (and nothing else)
| What | HealthKit type | Used for |
|---|---|---|
| Heart rate for 3 minutes after each cycling workout | heartRate (same watch, after the workout's end) | Heart-rate recovery after the ride |
| VO2 max | vo2Max | Fitness trend |
| HRV (SDNN) | heartRateVariabilitySDNN | Recovery status |
| Resting heart rate | restingHeartRate | Recovery status |
| Cardio Recovery | heartRateRecoveryOneMinute | Apple's own one-minute drop, shown as its own trend |

Never sleep, other workouts, or anything else. Recovery data is never shown to other people, whatever
`SOURCE_POLICY` says. Disconnecting Apple Health deletes it from the server, including the batches as received.

## How it flows
- **After-ride heart rate** rides along with each workout upload (`"after"` in the recording JSON). The merge
  keeps the wearable's figure as `hr_drop_60s` / `hr_drop_120s` on the ride (end = average of the last 30 s).
- **Readings** go up in batches (`POST /v1/metrics/apple_health`, format `rideengine.metrics/1`), one
  anchored query per type, the first time going back two years. Repeats are ignored (by HealthKit id);
  unknown kinds and unbelievable values are dropped.
- **`GET /v1/recovery`** (`rideengine/analysis/wellness.py`): for HRV and resting heart rate, the last 7 days
  against the rider's own usual range (mean ± 1 SD of the 60 days before, 14+ days of readings needed);
  a one-line readiness from the two together; VO2 max latest and 90-day change; heart-rate recovery after
  rides, best, and whether it's getting faster. Ride notes add "your fastest heart-rate recovery yet".
- Rule-based text, always "training guidance from your own data, not medical advice".

## Things to know
- Apple Watch estimates **VO2 max from outdoor walks, runs and hikes, not rides**, so a rider who only
  rides may have few readings. Once the KICKR gives power, an estimate from best 5-minute power can join it.
- **HRV** is mostly measured overnight and in the background: wear the watch to bed for it to mean much.
- **After-ride heart rate** only exists if the watch keeps measuring after the workout ends. Whether it does
  for cycling workouts needs checking on Neelay's phone.
- Existing riders see **Allow recovery data** on the Apple Health card (the new types need their own
  permission); the readings then sync.
