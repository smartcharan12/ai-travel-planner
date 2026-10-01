#!/bin/sh
# One-shot Kibana setup, run by the `elk-setup` service in docker-compose (curl image).
# Creates the data view and a few saved Discover searches. Safe to re-run (overwrite=true).
# Untested against a live Kibana by the author (Docker was unavailable); see docs/20_elk_stack.md
# for the equivalent manual steps.
set -eu

KIBANA="${KIBANA_URL:-http://kibana:5601}"
DATA_VIEW_ID="travel-planner-logs"

echo "waiting for Kibana at $KIBANA ..."
until curl -fs "$KIBANA/api/status" >/dev/null; do sleep 5; done

echo "creating data view travel-planner-logs-*"
curl -fsS -X POST "$KIBANA/api/data_views/data_view" \
  -H 'kbn-xsrf: true' -H 'Content-Type: application/json' \
  -d "{\"override\": true, \"data_view\": {\"id\": \"$DATA_VIEW_ID\", \"title\": \"travel-planner-logs-*\",
       \"name\": \"Travel planner logs\", \"timeFieldName\": \"@timestamp\"}}" >/dev/null

# saved_search <id> <title> <KQL query> <comma-separated columns>
saved_search() {
  cols=$(printf '"%s",' $(echo "$4" | tr ',' ' ') | sed 's/,$//')
  query=$(printf '%s' "$3" | sed 's/"/\\\\\\"/g')
  curl -fsS -X POST "$KIBANA/api/saved_objects/search/$1?overwrite=true" \
    -H 'kbn-xsrf: true' -H 'Content-Type: application/json' \
    -d "{\"attributes\": {\"title\": \"$2\", \"columns\": [$cols], \"sort\": [[\"@timestamp\", \"desc\"]],
         \"kibanaSavedObjectMeta\": {\"searchSourceJSON\": \"{\\\"query\\\":{\\\"query\\\":\\\"$query\\\",\\\"language\\\":\\\"kuery\\\"},\\\"filter\\\":[],\\\"indexRefName\\\":\\\"kibanaSavedObjectMeta.searchSourceJSON.index\\\"}\"}},
         \"references\": [{\"name\": \"kibanaSavedObjectMeta.searchSourceJSON.index\", \"type\": \"index-pattern\", \"id\": \"$DATA_VIEW_ID\"}]}" >/dev/null
  echo "saved search: $2"
}

saved_search tp-requests "Requests" 'event_type : "request_completed"' "route,status,latency_ms,destination,error_code"
saved_search tp-errors "Failed requests" 'event_type : "request_completed" and status >= 400' "route,status,error_code,request_id"
saved_search tp-llm-failures "LLM call failures" 'event_type : "llm_call" and not outcome : "ok"' "purpose,model,outcome,error_type,latency_ms"
saved_search tp-search-failures "Search failures" 'event_type : "search_call" and outcome : "error"' "provider,category,error_code,latency_ms"
saved_search tp-repairs "Itinerary repairs" 'event_type : ("itinerary_repair_requested" or "itinerary_invalid")' "event_type,attempt,reasons,error_codes"
saved_search tp-plans "Completed plans" 'event_type : "plan_completed"' "destination,num_days,llm_calls,repair_attempts,total_latency_ms"

echo "Kibana setup complete: open http://localhost:5601 -> Discover"
