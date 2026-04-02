"""
Multi-cluster support for KubeSpawner.

This module provides experimental support for spawning notebooks across
multiple Kubernetes clusters using different kubeconfig contexts.
"""

from .spawner import MultiClusterKubeSpawner

__all__ = ["MultiClusterKubeSpawner"]
