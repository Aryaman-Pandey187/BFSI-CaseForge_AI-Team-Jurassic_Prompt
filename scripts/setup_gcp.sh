#!/usr/bin/env bash
# =============================================================================
# One-time Google Cloud setup for CaseForge AI.
#   PROJECT_ID=my-proj REGION=asia-south1 ./scripts/setup_gcp.sh
# Enables APIs, creates Firestore (Native), a least-privilege service account,
# and Secret Manager secrets for Twilio credentials.
# =============================================================================
set -euo pipefail
PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
FIRESTORE_LOCATION="${FIRESTORE_LOCATION:-$REGION}"
SA_NAME="${SA_NAME:-caseforge-sa}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> Project: $PROJECT_ID  Region: $REGION"
gcloud config set project "$PROJECT_ID" >/dev/null

echo "==> Enabling APIs (takes ~1-2 min)"
gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  aiplatform.googleapis.com speech.googleapis.com texttospeech.googleapis.com \
  firestore.googleapis.com secretmanager.googleapis.com logging.googleapis.com

echo "==> Firestore (Native mode) database"
if ! gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  gcloud firestore databases create --location="$FIRESTORE_LOCATION" --type=firestore-native
else
  echo "    (default) database already exists"
fi

echo "==> Service account $SA_EMAIL"
gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" --display-name="CaseForge AI runtime"
for role in roles/aiplatform.user roles/datastore.user roles/secretmanager.secretAccessor \
            roles/logging.logWriter roles/speech.client; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA_EMAIL" \
    --role="$role" --condition=None >/dev/null 2>&1 || \
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA_EMAIL" --role="$role" >/dev/null
  echo "    granted $role"
done
# Cloud TTS needs no IAM role beyond the API being enabled for the project.

create_secret() {  # name value
  local name="$1" value="$2"
  if gcloud secrets describe "$name" >/dev/null 2>&1; then
    printf '%s' "$value" | gcloud secrets versions add "$name" --data-file=- >/dev/null
  else
    printf '%s' "$value" | gcloud secrets create "$name" --replication-policy=automatic --data-file=- >/dev/null
  fi
  echo "    secret $name stored"
}

echo "==> Secret Manager"
if [[ -z "${TWILIO_ACCOUNT_SID:-}" ]]; then read -rp "Twilio Account SID: " TWILIO_ACCOUNT_SID; fi
if [[ -z "${TWILIO_AUTH_TOKEN:-}" ]]; then read -rsp "Twilio Auth Token: " TWILIO_AUTH_TOKEN; echo; fi
create_secret twilio-account-sid "$TWILIO_ACCOUNT_SID"
create_secret twilio-auth-token "$TWILIO_AUTH_TOKEN"
if [[ -n "${GEMINI_API_KEY:-}" ]]; then create_secret gemini-api-key "$GEMINI_API_KEY"; fi

echo
echo "Done. Next:"
echo "  1) Seed Firestore:   (cd backend && GOOGLE_CLOUD_PROJECT=$PROJECT_ID python -m app.seed)   # or let AUTO_SEED do it"
echo "  2) Deploy:           PROJECT_ID=$PROJECT_ID REGION=$REGION ./scripts/deploy_cloud_run.sh"
