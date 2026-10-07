FROM mcr.microsoft.com/devcontainers/base:ubuntu26.04

# Prevent interactive prompts during apt installations
ENV DEBIAN_FRONTEND=noninteractive \
    HELM_PLUGINS=/usr/local/share/helm/plugins \
    HELM_CACHE_HOME=/usr/local/share/helm/cache \
    HELM_CONFIG_HOME=/usr/local/share/helm/config \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# Install base utilities, Python tooling, and Yamllint
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash-completion \
    ca-certificates \
    curl \
    git \
    gnupg \
    jq \
    less \
    make \
    nano \
    procps \
    python3 \
    python3-pip \
    python3-venv \
    rsync \
    sudo \
    tar \
    unzip \
    vim \
    wget \
    yamllint \
    && echo "vscode ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/vscode \
    && chmod 0440 /etc/sudoers.d/vscode \
    && pip3 install --no-cache-dir --break-system-packages yamale \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Helm 3
RUN curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash \
    && helm version

# Install Kubectl (latest 1.33 release, compatible with k8s 1.32 server within +-1 minor version window)
RUN KUBECTL_VER=$(curl -fsSL https://dl.k8s.io/release/stable-1.33.txt) \
    && curl -fsSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VER}/bin/linux/amd64/kubectl" \
    && chmod +x /usr/local/bin/kubectl \
    && kubectl version --client

# Install yq
RUN curl -fsSL -o /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 \
    && chmod +x /usr/local/bin/yq \
    && yq --version

# Install kubeconform
RUN KUBECONFORM_VER=$(curl -fsSL https://api.github.com/repos/yannh/kubeconform/releases/latest | jq -r .tag_name) \
    && curl -fsSL "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VER}/kubeconform-linux-amd64.tar.gz" | tar -xz -C /usr/local/bin kubeconform \
    && chmod +x /usr/local/bin/kubeconform \
    && kubeconform -v

# Install helm-docs
RUN HELM_DOCS_VER=$(curl -fsSL https://api.github.com/repos/norwoodj/helm-docs/releases/latest | jq -r .tag_name) \
    && curl -fsSL "https://github.com/norwoodj/helm-docs/releases/download/${HELM_DOCS_VER}/helm-docs_${HELM_DOCS_VER#v}_Linux_x86_64.tar.gz" | tar -xz -C /usr/local/bin helm-docs \
    && chmod +x /usr/local/bin/helm-docs \
    && helm-docs --version

# Install chart-testing (ct) and default schemas
RUN CT_VER=$(curl -fsSL https://api.github.com/repos/helm/chart-testing/releases/latest | jq -r .tag_name) \
    && mkdir -p /tmp/ct \
    && curl -fsSL "https://github.com/helm/chart-testing/releases/download/${CT_VER}/chart-testing_${CT_VER#v}_linux_amd64.tar.gz" | tar -xz -C /tmp/ct \
    && mv /tmp/ct/ct /usr/local/bin/ct \
    && chmod +x /usr/local/bin/ct \
    && mkdir -p /etc/ct \
    && mv /tmp/ct/etc/* /etc/ct/ \
    && rm -rf /tmp/ct \
    && ct version

# Setup system-wide Helm plugins (helm-diff and helm-unittest)
RUN mkdir -p /usr/local/share/helm/plugins \
    && helm plugin install https://github.com/databus23/helm-diff \
    && helm plugin install https://github.com/helm-unittest/helm-unittest \
    && chmod -R 755 /usr/local/share/helm/plugins \
    && helm plugin list

# Configure bash completion and git safe directory
RUN mkdir -p /etc/bash_completion.d \
    && helm completion bash > /etc/bash_completion.d/helm \
    && kubectl completion bash > /etc/bash_completion.d/kubectl \
    && git config --system --add safe.directory '*'

# Pre-configure MassBank helm repo for user vscode
RUN mkdir -p "${HELM_CACHE_HOME}" "${HELM_CONFIG_HOME}" \
    && chown -R vscode:vscode "${HELM_CACHE_HOME}" "${HELM_CONFIG_HOME}" \
    && su - vscode -c "HELM_CACHE_HOME=${HELM_CACHE_HOME} HELM_CONFIG_HOME=${HELM_CONFIG_HOME} helm repo add massbank https://massbank.github.io/MassBank-charts 2>/dev/null || true" \
    && su - vscode -c "HELM_CACHE_HOME=${HELM_CACHE_HOME} HELM_CONFIG_HOME=${HELM_CONFIG_HOME} helm repo update 2>/dev/null || true"

WORKDIR /workspaces/MassBank-charts
USER vscode
