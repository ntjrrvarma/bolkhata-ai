#!/usr/bin/env bash
# ============================================================================
# BolKhata AI — Google Cloud Run Deployment Script (`asia-south1` / Mumbai)
# Build with Google Gemini Hackathon (PS 04: Open Innovation)
# ============================================================================

set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
SERVICE_NAME="${SERVICE_NAME:-bolkhata-ai}"
REGION="asia-south1"
VERTEX_LOCATION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
GEMINI_MODEL="${GEMINI_LIVE_MODEL:-gemini-2.0-flash-live-preview-04-09}"
USE_MOCK="${USE_MOCK_DB:-false}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Error: GOOGLE_CLOUD_PROJECT is not set. Export GOOGLE_CLOUD_PROJECT=your-project-id first."
  exit 1
fi

echo "Deploying ${SERVICE_NAME} to Google Cloud Run (Project: ${PROJECT_ID}, Region: ${REGION})..."

gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 2 \
  --memory 1Gi \
  --timeout 900 \
  --session-affinity \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${VERTEX_LOCATION},GEMINI_LIVE_MODEL=${GEMINI_MODEL},USE_MOCK_DB=${USE_MOCK}"

echo "Deployment complete!"
gcloud run services describe "${SERVICE_NAME}" --project "${PROJECT_ID}" --region "${REGION}" --format="value(status.url)"
