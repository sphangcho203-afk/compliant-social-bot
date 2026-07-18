# Dashboard job history

The local dashboard now includes a searchable history page at:

```text
http://127.0.0.1:8765/history
```

The page is read-only and works whether or not queue controls are enabled.

## Search

Use the search box to match text stored in job metadata, including titles, local video paths, job kinds, and recorded errors.

## Filters

Filter by job status:

- queued
- running
- done
- failed
- cancelled

Filter by time window:

- today
- last 7 days
- last 30 days
- all time

Filters can be combined with search text.

## Statistics

The history page shows total jobs, completed jobs, failed jobs, and the current completion rate across all stored jobs.

## Job details

Select a job ID to open its detail page. The detail view includes:

- queue state and approval status
- attempts, schedule, and timestamps
- local media path and privacy setting
- last recorded error
- publication ID and URL when available
- latest stored views, likes, and comments when available

The history pages do not approve, cancel, retry, publish, or alter credentials.
