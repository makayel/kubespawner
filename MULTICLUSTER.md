# Multi-Cluster KubeSpawner Development Environment

This guide explains how to set up a multi-cluster development environment using k0s on two nodes (kube01, kube02).

## Prerequisites

- Two Linux nodes (kube01, kube02) with network connectivity
- SSH access to both nodes
- Python 3.10+ with virtual environment support

## Cluster Setup

### Step 1: Install k0s on Both Nodes

Run on **both kube01 and kube02**:

```bash
curl -sSLf https://get.k0s.sh | sudo sh
sudo k0s install controller --single
sudo k0s start
```

### Step 2: Configure kubectl Access

On your **development machine** (or either node):

```bash
# Copy kubeconfig from the controller node
sudo scp /var/lib/k0s/pki/admin.conf ~/.kube/config
mkdir -p ~/.kube
sudo cp /var/lib/k0s/pki/admin.conf ~/.kube/config
chmod 600 ~/.kube/config
```

### Step 3: Install and Configure MetalLB

MetalLB provides LoadBalancer service support for bare-metal clusters.

#### Install MetalLB

```bash
# On one of the k0s nodes
sudo k0s kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.14.5/config/manifests/metallb-native.yaml
sudo k0s kubectl get pods -n metallb-system
```

#### Configure IP Address Pool

Create `/home/k0s/metallb-config.yaml`:

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: default-pool
  namespace: metallb-system
spec:
  addresses:
  - 192.168.1.10-192.168.1.30  # <-- Change to your network range
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: default
  namespace: metallb-system
```

**Multi-Cluster Setup:** If using multiple k0s clusters (e.g., kube01 and kube02), ensure each cluster's MetalLB IP pool uses **non-overlapping IP ranges**. For example:

- **kube01:** `192.168.1.10-192.168.1.30`
- **kube02:** `192.168.1.31-192.168.1.50`

Overlapping ranges will cause IP conflicts and LoadBalancer services to fail.

Apply the configuration:

```bash
sudo k0s kubectl apply -f /home/k0s/metallb-config.yaml
```

### Step 4: Test LoadBalancer Services

```bash
# Create a test service
sudo k0s kubectl create deployment nginx --image=nginx
sudo k0s kubectl expose deployment nginx --type=LoadBalancer --port=80

# Get the external IP
sudo k0s kubectl get svc

# Clean up
sudo k0s kubectl delete svc nginx
sudo k0s kubectl delete deployment nginx
```

### Step 5: Install Longhorn Storage (Optional)

Longhorn provides persistent volume support.

```bash
# Install dependencies
sudo apt update
sudo apt install -y open-iscsi nfs-common
sudo systemctl enable --now iscsid
sudo modprobe iscsi_tcp
echo iscsi_tcp | sudo tee -a /etc/modules

# Verify mount propagation
findmnt -o TARGET,PROPAGATION /

# Install Longhorn
sudo k0s kubectl apply -f https://raw.githubusercontent.com/longhorn/longhorn/v1.6.0/deploy/longhorn.yaml

# Check storage classes
sudo k0s kubectl get storageclass

# Monitor Longhorn pods
watch -n1 'sudo k0s kubectl -n longhorn-system get pods'
```

## Multi-Cluster Configuration

### Configure Multiple Kubeconfig Contexts

After setting up both clusters, configure your kubeconfig with multiple contexts:

```bash
# Copy kubeconfig from second cluster
sudo scp kube02:/var/lib/k0s/pki/admin.conf ~/.kube/config-kube02

# Merge contexts
kubectl config --kubeconfig=~/.kube/config-kube02 view --raw > /tmp/kube02-context
kubectl config --kubeconfig=~/.kube/config view --raw > /tmp/kube01-context

# Combine into single kubeconfig
cat /tmp/kube01-context /tmp/kube02-context > ~/.kube/config-multi
```

### JupyterHub Multi-Cluster Configuration

Create `jupyterhub_multi_config.py` based on `jupyterhub_config.py` with the following changes:

#### Key Differences from Base Configuration

1. **Spawner Class**: Changed from `kubespawner.KubeSpawner` to `MultiClusterKubeSpawner`:
   ```python
   # jupyterhub_config.py (base)
   c.JupyterHub.spawner_class = 'kubespawner.KubeSpawner'

   # jupyterhub_multi_config.py (multi-cluster)
   c.JupyterHub.spawner_class = 'kubespawner.multicluster.spawner.MultiClusterKubeSpawner'
   ```

2. **Profile-Based kube_context**: Each profile can specify a `kube_context` in `kubespawner_override`:
   ```python
   c.KubeSpawner.profile_list = [
       {
           'display_name': 'Cluster 1 - small',
           'slug': 'c1.small',
           'default': True,
           'kubespawner_override': {
               'kube_context': 'cluster01',  # <-- Cluster-specific context
               'cpu_limit': 1,
           }
       },
       {
           'display_name': 'Cluster 2 - small',
           'slug': 'c2.small',
           'kubespawner_override': {
               'kube_context': 'cluster02',  # <-- Different cluster
               'cpu_limit': 1,
           }
       }
   ]
   ```

3. **Storage Configuration** (optional): Enable persistent storage:
   ```python
   c.KubeSpawner.storage_pvc_ensure = True
   c.KubeSpawner.storage_capacity = '1Gi'
   c.KubeSpawner.pvc_name_template = 'claim-jupyterhub-{user_server}'
   ```

4. **Security Context** (optional): Set pod security context:
   ```python
   c.KubeSpawner.pod_security_context = {"fsGroup": 100}
   c.KubeSpawner.container_security_context = {"runAsUser": 1000, "runAsGroup": 100}
   ```

5. **Named Servers** (recommended): Enable users to run multiple servers:
   ```python
   c.JupyterHub.allow_named_servers = True
   ```

6. **Services** (recommended for multi-cluster): Enable service creation:
   ```python
   c.KubeSpawner.services_enabled = True
   ```

#### Example `jupyterhub_multi_config.py`

See `jupyterhub_multi_config.py` in the repository for a complete working example.

## Building the Package

To build a package with multi-cluster support:

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install build tools
pip install --upgrade build

# Build the package
python -m build
```

This creates:
- `dist/jupyterhub_kubespawner-*.whl` - Wheel distribution
- `dist/jupyterhub_kubespawner-*.tar.gz` - Source distribution

To install the built package:

```bash
pip install dist/jupyterhub_kubespawner-*.whl
```

## Development Setup

### Install kubespawner with multi-cluster support (editable)

```bash
# From the kubespawner repository
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

### Run Tests

```bash
pytest
```

### Run Local JupyterHub

```bash
# Install dependencies
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[test]"

# Install configurable-http-proxy
npm install configurable-http-proxy
export PATH=$(pwd)/node_modules/.bin:$PATH

# Start JupyterHub with multi-cluster config
jupyterhub --config=jupyterhub_multi_config.py
```

## Troubleshooting

### Check MetalLB Status

```bash
sudo k0s kubectl get pods -n metallb-system
sudo k0s kubectl describe pods -n metallb-system
```

### Check LoadBalancer IP Assignment

```bash
# Watch for external IP assignment
watch -n1 'sudo k0s kubectl get svc'
```

### Verify Cluster Connectivity

```bash
# List nodes in each cluster
sudo k0s kubectl get nodes
sudo k0s kubectl --context=k0s-kube02 get nodes
```
