# ROSA CAPA E2E Test Runner
#
# ci-operator builds this via dockerfile_path and provides it as `rosa-capa-e2e`.
# For local testing: podman build -t rosa-capa-e2e:test .

# ── Stage 1: builder ─────────────────────────────────────────────
FROM registry.access.redhat.com/ubi9/ubi:latest AS builder

ARG OC_VERSION=stable
ARG HELM_VERSION=v3.16.0
ARG KUBECTL_VERSION=v1.35.2

# Install system dependencies
RUN dnf install -y --allowerasing \
    python3 python3-pip python3-devel gcc \
    git curl tar \
    && dnf clean all

# Install Python packages into a venv
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir \
    ansible-core \
    boto3 botocore \
    kubernetes openshift \
    PyYAML jinja2

# Install oc
RUN curl -fsSL "https://mirror.openshift.com/pub/openshift-v4/clients/ocp/${OC_VERSION}/openshift-client-linux.tar.gz" -o /tmp/oc.tar.gz && \
    tar xz -C /usr/local/bin -f /tmp/oc.tar.gz oc && \
    chmod +x /usr/local/bin/oc && \
    rm -f /tmp/oc.tar.gz

# Install kubectl
RUN curl -fsSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" && \
    curl -fsSL -o /tmp/kubectl.sha256 "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl.sha256" && \
    echo "$(cat /tmp/kubectl.sha256)  /usr/local/bin/kubectl" | sha256sum -c && \
    chmod +x /usr/local/bin/kubectl && \
    rm -f /tmp/kubectl.sha256

# Install helm
RUN curl -fsSL -o /tmp/helm.tar.gz "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" && \
    curl -fsSL -o /tmp/helm.sha256sum "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz.sha256sum" && \
    echo "$(awk '{print $1}' /tmp/helm.sha256sum)  /tmp/helm.tar.gz" | sha256sum -c && \
    tar xz -C /tmp -f /tmp/helm.tar.gz && \
    mv /tmp/linux-amd64/helm /usr/local/bin/helm && chmod +x /usr/local/bin/helm && \
    rm -rf /tmp/helm.tar.gz /tmp/helm.sha256sum /tmp/linux-amd64


# ── Stage 2: runtime ─────────────────────────────────────────────
FROM registry.access.redhat.com/ubi9/ubi-minimal:latest

RUN microdnf install -y python3 git tar jq openssh-clients \
    && microdnf clean all

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /usr/local/bin/oc /usr/local/bin/oc
COPY --from=builder /usr/local/bin/kubectl /usr/local/bin/kubectl
COPY --from=builder /usr/local/bin/helm /usr/local/bin/helm

ENV PATH="/opt/venv/bin:$PATH"

RUN useradd -u 1001 -m -d /opt/app-root/src app-user
USER 1001
WORKDIR /opt/app-root/src
