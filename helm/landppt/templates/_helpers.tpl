{{/*
Expand the name of the chart.
*/}}
{{- define "landppt.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "landppt.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Chart label.
*/}}
{{- define "landppt.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "landppt.labels" -}}
helm.sh/chart: {{ include "landppt.chart" . }}
{{ include "landppt.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "landppt.selectorLabels" -}}
app.kubernetes.io/name: {{ include "landppt.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Database URL: internal StatefulSet or external.
*/}}
{{- define "landppt.databaseUrl" -}}
{{- if .Values.postgresql.enabled -}}
postgresql://{{ .Values.postgresql.auth.username }}:{{ .Values.postgresql.auth.password }}@{{ include "landppt.fullname" . }}-postgresql:5432/{{ .Values.postgresql.auth.database }}
{{- else -}}
{{ required "externalDatabase.url is required when postgresql.enabled=false" .Values.externalDatabase.url }}
{{- end -}}
{{- end }}

{{/*
Valkey URL: internal or external.
*/}}
{{- define "landppt.valkeyUrl" -}}
{{- if .Values.valkey.enabled -}}
valkey://{{ include "landppt.fullname" . }}-valkey:6379
{{- else -}}
{{ required "externalValkey.url is required when valkey.enabled=false" .Values.externalValkey.url }}
{{- end -}}
{{- end }}
