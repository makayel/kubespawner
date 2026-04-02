import asyncio
import sys

from kubernetes_asyncio import client
from kubernetes_asyncio.client.rest import ApiException
from kubernetes_asyncio.config import kube_config
from traitlets import Tuple, Type, Unicode
from typing import Optional
from unittest.mock import patch

from .reflector import MultiResourceReflector
from ..spawner import KubeSpawner, MockObject

class PodReflector(MultiResourceReflector):
  """
  PodReflector is merely a configured ResourceReflector. It exposes
  the pods property, which is simply mapping to self.resources where the
  ResourceReflector keeps an updated list of the resource defined by
  the `kind` field and the `list_method_name` field.
  """

  kind = "pods"

  @property
  def pods(self):
    """
    A dictionary of pods for the namespace as returned by the Kubernetes
    API. The dictionary keys are the pod ids and the values are
    dictionaries of the actual pod resource values.

    ref: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.28/#pod-v1-core
    """
    return self.resources

class EventReflector(MultiResourceReflector):
  """
  EventsReflector is merely a configured ResourceReflector. It
  exposes the events property, which is simply mapping to self.resources where
  the ResourceReflector keeps an updated list of the resource
  defined by the `kind` field and the `list_method_name` field.
  """

  kind = "events"

  @property
  def events(self):
    """
    Returns list of dictionaries representing the k8s
    events within the namespace, sorted by the latest event.

    ref: https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.28/#event-v1-core
    """

    # NOTE:
    # - self.resources is a dictionary with keys mapping unique ids of
    #   Kubernetes Event resources, updated by ResourceReflector.
    #   self.resources will builds up with incoming k8s events, but can also
    #   suddenly refreshes itself entirely. We should not assume a call to
    #   this dictionary's values will result in a consistently ordered list,
    #   so we sort it to get it somewhat more structured.
    # - We either seem to get only event['lastTimestamp'] or
    #   event['eventTime'], both fields serve the same role but the former
    #   is a low resolution timestamp without and the other is a higher
    #   resolution timestamp.
    return sorted(
      self.resources.values(),
      key=lambda event: event["lastTimestamp"] or event["eventTime"],
    )

class MultiClusterKubeSpawner(KubeSpawner):
  kube_context = Unicode(
    None,
    allow_none=True,
    config=True,
    help=""",
    The Kubernetes context to use for this spawner. If not specified, the default context will be used.
    """,
  )

  multicluster_pod_scheme = ""
  multicluster_pod_ip = ""
  multicluster_pod_port = ""

  # Override
  def _get_reflector_key(self, kind: str) -> Tuple[str, str, str, Optional[str]]:
    if self.enable_user_namespaces:
      # one reflector for all namespaces
      return (self.kube_context, kind, None)

    return (self.kube_context, kind, self.namespace)

  @property
  def pod_reflector(self):
    """
    Returns instance of ResourceReflector for pods.
    """
    key = self._get_reflector_key('pods')
    return self.__class__.reflectors.get(key, None)

  @property
  def event_reflector(self):
    """
    Returns instance of ResourceReflector for events, if the
    spawner instance has events_enabled.
    """
    if self.events_enabled:
      key = self._get_reflector_key('events')
      return self.__class__.reflectors.get(key, None)
    return None

  async def _start_reflector(
      self,
      kind: str,
      reflector_class: Type[MultiResourceReflector],
      replace: bool = False,
      **kwargs,
  ):
      """Start a shared reflector on the KubeSpawner class

      kind: used to generate key to store reflector shared instance (e.g. 'pod' or 'events')
      reflector_class: Reflector class to be instantiated
      kwargs: extra keyword-args to be relayed to ReflectorClass

      If replace=False and the pod reflector is already running,
      do nothing.

      If replace=True, a running pod reflector will be stopped
      and a new one started (for recovering from possible errors).
      """

      key = self._get_reflector_key(kind)
      previous_reflector = self.__class__.reflectors.get(key, None)

      if previous_reflector and not replace:
          # fast path
          if not previous_reflector.first_load_future.done():
              # make sure it's loaded, so subsequent calls to start_reflector
              # don't finish before the first
              await previous_reflector.first_load_future
          return previous_reflector

      if self.enable_user_namespaces:
          # Create one reflector for all namespaces.
          # This requires binding ServiceAccount to ClusterRole.

          def on_reflector_failure():
              # If reflector cannot be started, halt the JH application.
              self.log.critical(
                  "Reflector with key %r failed, halting Hub.",
                  key,
              )
              sys.exit(1)

          async def catch_reflector_start(func):
              try:
                  await func
              except Exception:
                  self.log.exception(f"Reflector with key {key} failed to start.")
                  sys.exit(1)

      else:
          # Create a dedicated reflector for each namespace.
          # This allows JH to run pods in multiple namespaces without binding ServiceAccount to ClusterRole.

          on_reflector_failure = None

          async def catch_reflector_start(func):
              # If reflector cannot be started (e.g. insufficient access rights, namespace cannot be found),
              # just raise an exception instead halting the entire JH application.
              try:
                  await func
              except Exception:
                  self.log.exception(f"Reflector with key {key} failed to start.")
                  raise

      self.__class__.reflectors[key] = current_reflector = reflector_class(
          parent=self,
          namespace=self.namespace,
          on_failure=on_reflector_failure,
          **kwargs,
      )
      await catch_reflector_start(current_reflector.start())

      if previous_reflector:
          # we replaced the reflector, stop the old one
          await asyncio.ensure_future(previous_reflector.stop())

      # wait for first load
      await current_reflector.first_load_future

      # return the current reflector
      return current_reflector

  async def _start_watching_events(self, replace=False):
    """Start the events reflector

    If replace=False and the event reflector is already running,
    do nothing.

    If replace=True, a running pod reflector will be stopped
    and a new one started (for recovering from possible errors).
    """
    return await self._start_reflector(
      kind="events",
      reflector_class=EventReflector,
      fields={"involvedObject.kind": "Pod"},
      omit_namespace=self.enable_user_namespaces,
      replace=replace,
    )

  async def _start_watching_pods(self, replace=False):
    """Start the pods reflector

    If replace=False and the pod reflector is already running,
    do nothing.

    If replace=True, a running pod reflector will be stopped
    and a new one started (for recovering from possible errors).
    """
    return await self._start_reflector(
        kind="pods",
        reflector_class=PodReflector,
        # NOTE: We monitor resources with the old component label instead of
        #       the modern app.kubernetes.io/component label. A change here
        #       is only non-breaking if we can assume the running resources
        #       monitored can be detected by either old or new labels.
        #
        #       The modern labels were added to resources created by
        #       KubeSpawner 7 first adopted in z2jh 4.0.
        #
        #       Related to https://github.com/jupyterhub/kubespawner/issues/834
        #
        labels={"component": self.component_label},
        omit_namespace=self.enable_user_namespaces,
        replace=replace,
    )

  def _get_pod_url(self, pod=None):
    return "{}://{}:{}".format(self.multicluster_pod_scheme, self.multicluster_pod_ip, self.multicluster_pod_port)

  # Client
  async def _get_api_client(self):
    """
    Return a Kubernetes API client configured for the selected context.
    This avoids global state and allows multi-cluster support.
    """
    if self.profile_list:
      for profile in self.profile_list:
        if profile.get("slug") == self.user_options.get("profile"):
          if 'kube_context' in profile.get('kubespawner_override', {}):
            self.kube_context = profile['kubespawner_override']['kube_context']
            return await kube_config.new_client_from_config(context=self.kube_context)

    # Fallback: use default context if no profile match or kube_context not specified
    self.kube_context = None
    return await kube_config.new_client_from_config()

  async def _get_k8s_apis(self):
    """
    Initialize all Kubernetes API clients with the proper configuration.
    """
    api_client = await self._get_api_client()
    
    return {
      "core": client.CoreV1Api(api_client),
      "apps": client.AppsV1Api(api_client),
      "networking": client.NetworkingV1Api(api_client),
      "custom": client.CustomObjectsApi(api_client),
    }

  # Spawner
  # class MockObject:
  #   pass

  def __init__(self, *args, **kwargs):
    # Pop _mock before calling super().__init__() so it can be handled by parent
    _mock = kwargs.pop('_mock', False)

    # Set up mock objects BEFORE calling super().__init__() so parent can use them
    # when expanding user properties
    if _mock:
      # runs during test execution only - set up mock objects
      # if user is not provided, create a mock user
      if 'user' not in kwargs:
        user = MockObject()
        user.name = 'mock@name'
        user.id = 'mock_id'
        user.url = 'mock_url'
        kwargs['user'] = user

      # if hub is not provided, create a mock hub
      if 'hub' not in kwargs:
        hub = MockObject()
        hub.public_host = 'mock_public_host'
        hub.url = 'mock_url'
        hub.base_url = 'mock_base_url'
        hub.api_url = 'mock_api_url'
        kwargs['hub'] = hub

      # Patch shared_client to return a mock object to avoid issues with
      # requiring a running event loop
      mock_api = MockObject()
      import kubespawner.spawner
      import kubespawner.clients

      original_shared_client = kubespawner.clients.shared_client
      kubespawner.clients.shared_client = lambda *args, **kwargs: mock_api
      kubespawner.spawner.shared_client = lambda *args, **kwargs: mock_api

      try:
        super().__init__(*args, **kwargs)
      finally:
        # Restore original shared_client
        kubespawner.clients.shared_client = original_shared_client
        kubespawner.spawner.shared_client = original_shared_client
    else:
      super().__init__(*args, **kwargs)

  async def _get_service(self, timeout=600):
    for _ in range(timeout):
      try:
        service = await self.api.read_namespaced_service(namespace=self.namespace, name=self.pod_name)
        return service
      except Exception:
        await asyncio.sleep(1)

    raise TimeoutError(f"Service {self.pod_name} not in ### state after {timeout}s")

  async def _custom_get_pod_url(self, pod=None):
    """
    Get pod URL from external load balancer service.

    This method extracts the scheme, IP, and port from a Kubernetes Service
    with an external load balancer. For services without load balancer ingress,
    it falls back to the service cluster IP.
    """
    service = await self._get_service()

    # Get port info
    port = service.spec.ports[0]
    self.multicluster_pod_port = port.port

    # Determine scheme from protocol (http/https)
    port_protocol = getattr(port, 'protocol', 'TCP')
    self.multicluster_pod_scheme = 'https' if port_protocol == 'TCP' else 'http'

    # Get IP from load balancer ingress if available, otherwise use cluster IP
    if service.status.load_balancer.ingress and len(service.status.load_balancer.ingress) > 0:
      self.multicluster_pod_ip = service.status.load_balancer.ingress[0].ip
    else:
      # Fallback to service cluster IP if no external load balancer
      self.multicluster_pod_ip = service.spec.cluster_ip

  async def _start(self):
    apis = await self._get_k8s_apis()
    self.api = apis["core"]
    self.apps_api = apis["apps"]
    self.networking_api = apis["networking"]
    self.custom_api = apis["custom"]

    self.extra_labels = {
      'hub.jupyter.org/kube_context': self.kube_context,
    }
    
    self._pvc_exists = await self._check_pvc_exists(self.pvc_name, self.namespace)

    await super()._start()
    await self._custom_get_pod_url()

    return self.multicluster_pod_ip, self.multicluster_pod_port
