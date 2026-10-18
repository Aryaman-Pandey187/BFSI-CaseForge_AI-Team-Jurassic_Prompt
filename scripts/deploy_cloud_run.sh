#!/usr/bin/env bash
# =============================================================================
# Build + deploy CaseForge AI to Cloud Run (single service: API + websockets + UI)
#   PROJECT_ID=my-proj REGION=asia-south1 ./scripts/deploy_cloud_run.sh
# Optional: TWILIO_NUMBER=+1415... to point that number's webhook at the new URL.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-caseforge}"
SA_EMAIL="${SA_EMAIL:-caseforge-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
LLM_MODE="${LLM_MODE:-vertex}"
GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.5-flash}"
VOICE_MODE="${VOICE_MODE:-media_stream}"

# '@' separates variables (gcloud ^@^ delimiter syntax) so values may contain commas.
ENV_VARS="APP_ENV=prod@GOOGLE_CLOUD_PROJECT=${PROJECT_ID}@GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION:-global}"
ENV_VARS+="@LLM_MODE=${LLM_MODE}@GEMINI_MODEL=${GEMINI_MODEL}@GEMINI_FALLBACK_MODELS=${GEMINI_FALLBACK_MODELS:-gemini-3.1-flash-lite}"
ENV_VARS+="@DATA_BACKEND=firestore@AUTO_SEED=true@VOICE_MODE=${VOICE_MODE}@TTS_MODE=${TTS_MODE:-cloud}"
ENV_VARS+="@TTS_VOICE=${TTS_VOICE:-en-IN-Neural2-A}@STT_LANGUAGE=${STT_LANGUAGE:-en-IN}@TTS_LANGUAGE=${TTS_LANGUAGE:-en-IN}"
ENV_VARS+="@VALIDATE_TWILIO_SIGNATURE=${VALIDATE_TWILIO_SIGNATURE:-true}@BANK_NAME=${BANK_NAME:-Horizon Bank}"
[[ -n "${HANDOFF_NUMBER:-}" ]] && ENV_VARS+="@HANDOFF_NUMBER=${HANDOFF_NUMBER}"
[[ -n "${DEMO_TRUSTED_CALLER_NUMBERS:-}" ]] && ENV_VARS+="@DEMO_TRUSTED_CALLER_NUMBERS=${DEMO_TRUSTED_CALLER_NUMBERS}"

SECRETS="TWILIO_AUTH_TOKEN=twilio-auth-token:latest,TWILIO_ACCOUNT_SID=twilio-account-sid:latest"
[[ "$LLM_MODE" == "gemini_api" ]] && SECRETS+=",GEMINI_API_KEY=gemini-api-key:latest"

echo "==> Deploying $SERVICE to $REGION (builds the Dockerfile with Cloud Build)"
# Notes:
#  * max-instances=1 + session affinity: call state + desktop websockets live in one instance.
#  * no-cpu-throttling + min-instances=1: no cold start when the phone rings, STT streams keep running.
#  * timeout=3600: Cloud Run's max request duration, i.e. max websocket (call) length.
gcloud run deploy "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --source . \
  --service-account "$SA_EMAIL" --allow-unauthenticated \
  --min-instances 1 --max-instances 1 --session-affinity --no-cpu-throttling \
  --cpu 2 --memory 1Gi --timeout 3600 --concurrency 80 \
  --set-env-vars "^@^${ENV_VARS}" --set-secrets "$SECRETS"

URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"
echo "==> Setting PUBLIC_BASE_URL=$URL"
gcloud run services update "$SERVICE" --project "$PROJECT_ID" --region "$REGION" \
  --update-env-vars "PUBLIC_BASE_URL=${URL}" >/dev/null

echo
echo "Agent desktop : $URL"
echo "Voice webhook : $URL/twilio/voice   (HTTP POST)"
echo "Status cb     : $URL/twilio/status  (HTTP POST)"
if [[ -n "${TWILIO_NUMBER:-}" ]]; then
  python3 scripts/setup_twilio.py --base-url "$URL" --number "$TWILIO_NUMBER"
else
  echo "Point your Twilio number at it:  python3 scripts/setup_twilio.py --base-url $URL --number +1XXXXXXXXXX"
fi
