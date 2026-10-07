{{- define "im.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 50 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "im.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* Selector labels for one component. Call with (dict "root" . "component" "api"). */}}
{{- define "im.selectorLabels" -}}
app.kubernetes.io/name: {{ .root.Chart.Name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "im.backendImage" -}}
{{ .Values.image.backend.repository }}:{{ .Values.image.backend.tag | default .Chart.AppVersion }}
{{- end -}}

{{- define "im.frontendImage" -}}
{{ .Values.image.frontend.repository }}:{{ .Values.image.frontend.tag | default .Chart.AppVersion }}
{{- end -}}

{{- define "im.dbClusterName" -}}
{{ include "im.fullname" . }}-db
{{- end -}}

{{/* Secret holding the database URI: the one CloudNativePG generates, or an external one. */}}
{{- define "im.dbSecretName" -}}
{{- if .Values.postgres.enabled -}}
{{ include "im.dbClusterName" . }}-app
{{- else -}}
{{ required "externalDatabase.existingSecret is required when postgres.enabled is false" .Values.externalDatabase.existingSecret }}
{{- end -}}
{{- end -}}

{{/*
Spread a component's pods over zones and hosts. matchLabelKeys limits the calculation to
pods of the same ReplicaSet, so a rollout is not skewed by the old pods it is replacing.
*/}}
{{- define "im.topologySpread" -}}
topologySpreadConstraints:
  - topologyKey: topology.kubernetes.io/zone
    maxSkew: {{ .root.Values.topologySpread.zone.maxSkew }}
    whenUnsatisfiable: {{ .root.Values.topologySpread.zone.whenUnsatisfiable }}
    labelSelector:
      matchLabels:
        {{- include "im.selectorLabels" . | nindent 8 }}
    matchLabelKeys: [pod-template-hash]
  - topologyKey: kubernetes.io/hostname
    maxSkew: {{ .root.Values.topologySpread.host.maxSkew }}
    whenUnsatisfiable: {{ .root.Values.topologySpread.host.whenUnsatisfiable }}
    labelSelector:
      matchLabels:
        {{- include "im.selectorLabels" . | nindent 8 }}
    matchLabelKeys: [pod-template-hash]
{{- end -}}

{{- define "im.podSecurityContext" -}}
securityContext:
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault
{{- end -}}

{{- define "im.containerSecurityContext" -}}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: [ALL]
{{- end -}}

{{/* Environment shared by the API, the worker and the migration job. */}}
{{- define "im.backendEnv" -}}
envFrom:
  - configMapRef:
      name: {{ include "im.fullname" . }}-backend
env:
  - name: IM_DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: {{ include "im.dbSecretName" . }}
        key: uri
  - name: IM_WEBHOOK_TOKEN
    valueFrom:
      secretKeyRef:
        name: {{ .Values.existingSecret }}
        key: webhook-token
  - name: IM_SLACK_BOT_TOKEN
    valueFrom:
      secretKeyRef:
        name: {{ .Values.existingSecret }}
        key: slack-bot-token
        optional: true
  - name: IM_TELEGRAM_BOT_TOKEN
    valueFrom:
      secretKeyRef:
        name: {{ .Values.existingSecret }}
        key: telegram-bot-token
        optional: true
  - name: IM_SMTP_PASSWORD
    valueFrom:
      secretKeyRef:
        name: {{ .Values.existingSecret }}
        key: smtp-password
        optional: true
{{- end -}}
