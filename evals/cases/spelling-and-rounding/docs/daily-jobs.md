# Daily jobs

The backpu runs evrey night at 03:00 and writes to the restic repositry on
`/mnt/backup`. Its checked once a week, on Sundays at 05:00.

The morning summary is ready by 07:30, so its there when anyone gets up.

The health check runs shortly after 10:00, once the backup and the summary are
done, and warns when the last backup is older then two days.

The notes folder syncs every 15 minutes. A machine reboot, when a update needs
one, happens on Sundays at 04:30.
