# BigBlueprint

TJs 6th grade teacher posts the week's homework as a table in a Google Doc every Monday. We wrote this to dump the assignments into our family Google Calendar instead.

It might work for other classes if the teacher uses a similar weekly table (Mon through Fri columns, one CW row and one HW row per subject). If not, the parsing will need tweaking.

## How it works

The Google Doc is shared "anyone with the link", which means Google's plain text export endpoint will hand it over with no auth. The script grabs that, finds the weekly table, pulls out each homework cell, and writes an `.ics` file.

Due dates: if a line says "due Thursday" or "due tomorrow", that's used. Otherwise it defaults to whichever day's column the line appeared in. Same assignment showing up in multiple columns (typical for multi-day reminders) gets deduped.

The teacher's "week of" date is sometimes a Sunday, so the parser snaps to Monday before assigning column dates.

## Running it

```
python3 hw_to_ics.py
```

Stdlib only, no pip install. Prints a table and writes `homework.ics`. Then either double click the file or import it through Google Calendar's settings.

Flags: `--doc-id` if you want to point it at a different doc, `--out` to change the output path, `--format markdown` if you want a markdown table instead of ASCII, `--quiet` to skip the table.

## Pushing to Google Calendar automatically

For the auto-import I used [gcalcli](https://github.com/insanum/gcalcli). Setup is a pain (you have to create your own OAuth client in Google Cloud Console, add yourself as a test user, the whole dance) but it's a one time thing.

`run-weekly.sh` does the fetch + import. There's a launchd plist (`com.timlawrence.6a-homework.plist`) that fires it every Monday at 8 AM:

```
cp com.timlawrence.6a-homework.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.timlawrence.6a-homework.plist
```

If the Mac is asleep at 8 AM Monday, launchd runs it when the machine next wakes that day.

`launchctl start com.timlawrence.6a-homework` to fire it manually. Logs go to `weekly.log`.

## Things that are broken or fragile

Google Calendar's `.ics` import always appends. If I run this twice in a week, I get duplicate events. The Monday schedule mostly avoids this but if the teacher edits mid-week and I re-run, duplicates.

The "no homework" filter only catches a few exact phrases ("none", "n/a", "no hw"). Announcements like "NO POW THIS WEEK!" come through as events. I delete them by hand when they show up.

If the teacher restructures the table (adds a subject, changes the CW/HW order, etc.) parsing will break. The cell layout is hardcoded as "4 subjects, each with a subject-name cell + 5 CW cells + 5 HW cells".

The event UIDs are random per run (`uuid.uuid4`). I should probably make them stable so reimports could theoretically dedupe, though Google Calendar doesn't respect UIDs on import anyway.

## Files

- `hw_to_ics.py`: the parser/generator
- `run-weekly.sh`: wrapper for the Monday job
- `com.timlawrence.6a-homework.plist`: launchd schedule
- `homework.ics`: last generated calendar (gets overwritten each run)
- `weekly.log`: output from scheduled runs
