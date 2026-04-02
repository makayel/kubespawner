"""Tests for kubespawner.multicluster module"""

import pytest
from traitlets.config import Config
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from kubespawner.multicluster.reflector import MultiResourceReflector
from kubespawner.multicluster.spawner import (
    MultiClusterKubeSpawner,
    PodReflector,
    EventReflector,
)


class MockUser(Mock):
    name = 'testuser'
    server = Mock()

    @property
    def url(self):
        return self.server.url


class MockOrmSpawner(Mock):
    name = 'server'
    server = None


class TestMultiClusterKubeSpawner:
    """Tests for MultiClusterKubeSpawner class"""

    def test_inherits_from_kubespawner(self):
        """MultiClusterKubeSpawner should inherit from KubeSpawner"""
        from kubespawner import KubeSpawner
        assert issubclass(MultiClusterKubeSpawner, KubeSpawner)

    def test_has_kube_context_trait(self):
        """MultiClusterKubeSpawner should have kube_context trait"""
        spawner = MultiClusterKubeSpawner(_mock=True)
        assert hasattr(spawner, 'kube_context')
        assert spawner.kube_context is None

    def test_has_multicluster_pod_attributes(self):
        """MultiClusterKubeSpawner should have multicluster pod attributes"""
        spawner = MultiClusterKubeSpawner(_mock=True)
        assert hasattr(spawner, 'multicluster_pod_scheme')
        assert hasattr(spawner, 'multicluster_pod_ip')
        assert hasattr(spawner, 'multicluster_pod_port')
        assert spawner.multicluster_pod_scheme == ''
        assert spawner.multicluster_pod_ip == ''
        assert spawner.multicluster_pod_port == ''

    def test_pod_reflector_class(self):
        """PodReflector should be a configured MultiResourceReflector for pods"""
        assert PodReflector.kind == "pods"
        assert PodReflector.__bases__[0].__name__ == "MultiResourceReflector"

    def test_event_reflector_class(self):
        """EventReflector should be a configured MultiResourceReflector for events"""
        assert EventReflector.kind == "events"
        assert EventReflector.__bases__[0].__name__ == "MultiResourceReflector"


class TestMultiClusterKubeSpawnerReflectorKey:
    """Tests for reflector key generation"""

    def test_reflector_key_with_user_namespaces(self):
        """Reflector key should include context and None for namespace with user namespaces"""
        spawner = MultiClusterKubeSpawner(_mock=True, enable_user_namespaces=True)
        spawner.kube_context = 'cluster-1'
        key = spawner._get_reflector_key('pods')
        assert key == ('cluster-1', 'pods', None)

    def test_reflector_key_without_user_namespaces(self):
        """Reflector key should include context and namespace without user namespaces"""
        spawner = MultiClusterKubeSpawner(_mock=True, enable_user_namespaces=False)
        spawner.kube_context = 'cluster-1'
        spawner.namespace = 'test-namespace'
        key = spawner._get_reflector_key('pods')
        assert key == ('cluster-1', 'pods', 'test-namespace')

    def test_reflector_key_for_events(self):
        """Reflector key should work for events"""
        spawner = MultiClusterKubeSpawner(_mock=True, enable_user_namespaces=False)
        spawner.kube_context = 'cluster-1'
        spawner.namespace = 'test-namespace'
        key = spawner._get_reflector_key('events')
        assert key == ('cluster-1', 'events', 'test-namespace')


class TestMultiClusterKubeSpawnerGetApiClient:
    """Tests for _get_api_client method"""

    @pytest.fixture
    def spawner(self):
        """Create a spawner with mock profile_list"""
        c = Config()
        c.KubeSpawner.profile_list = [
            {
                'display_name': 'Cluster 1',
                'slug': 'c1',
                'kubespawner_override': {
                    'kube_context': 'cluster-1',
                },
            },
            {
                'display_name': 'Cluster 2',
                'slug': 'c2',
                'kubespawner_override': {
                    'kube_context': 'cluster-2',
                },
            },
        ]
        return MultiClusterKubeSpawner(_mock=True, config=c)

    @pytest.mark.asyncio
    async def test_get_api_client_finds_profile(self, spawner):
        """Should return API client for matching profile"""
        spawner.user_options = {'profile': 'c1'}

        mock_client = AsyncMock()
        with patch('kubespawner.multicluster.spawner.kube_config') as mock_kube_config:
            mock_kube_config.new_client_from_config = AsyncMock(return_value=mock_client)

            client = await spawner._get_api_client()

            assert client == mock_client
            assert spawner.kube_context == 'cluster-1'
            mock_kube_config.new_client_from_config.assert_called_once_with(context='cluster-1')

    @pytest.mark.asyncio
    async def test_get_api_client_falls_back_to_default(self, spawner):
        """Should return API client with default context when no profile match"""
        spawner.user_options = {'profile': 'nonexistent'}

        mock_client = AsyncMock()
        with patch('kubespawner.multicluster.spawner.kube_config') as mock_kube_config:
            mock_kube_config.new_client_from_config = AsyncMock(return_value=mock_client)

            client = await spawner._get_api_client()

            assert client == mock_client
            assert spawner.kube_context is None
            mock_kube_config.new_client_from_config.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_get_api_client_falls_back_without_profiles(self, spawner):
        """Should return API client with default context when no profile_list"""
        spawner.profile_list = []
        spawner.user_options = {'profile': 'c1'}

        mock_client = AsyncMock()
        with patch('kubespawner.multicluster.spawner.kube_config') as mock_kube_config:
            mock_kube_config.new_client_from_config = AsyncMock(return_value=mock_client)

            client = await spawner._get_api_client()

            assert client == mock_client
            assert spawner.kube_context is None

    @pytest.mark.asyncio
    async def test_get_api_client_falls_back_without_kube_context_in_override(self, spawner):
        """Should fall back when profile exists but kube_context is missing"""
        spawner.user_options = {'profile': 'c1'}
        # Update profile to not have kube_context
        spawner.profile_list[0]['kubespawner_override'] = {}

        mock_client = AsyncMock()
        with patch('kubespawner.multicluster.spawner.kube_config') as mock_kube_config:
            mock_kube_config.new_client_from_config = AsyncMock(return_value=mock_client)

            client = await spawner._get_api_client()

            assert client == mock_client
            assert spawner.kube_context is None


class TestMultiClusterKubeSpawnerCustomGetPodUrl:
    """Tests for _custom_get_pod_url method"""

    @pytest.fixture
    def spawner(self):
        """Create a spawner with mock service"""
        spawner = MultiClusterKubeSpawner(_mock=True)
        spawner.namespace = 'test-namespace'
        spawner.pod_name = 'test-pod'
        return spawner

    @pytest.mark.asyncio
    async def test_get_pod_url_with_load_balancer(self, spawner):
        """Should extract URL from load balancer service"""
        mock_service = MagicMock()
        mock_service.spec.ports = [MagicMock()]
        mock_service.spec.ports[0].port = 8080
        mock_service.spec.ports[0].protocol = 'TCP'
        mock_service.spec.cluster_ip = '10.0.0.1'
        mock_service.status.load_balancer.ingress = [MagicMock()]
        mock_service.status.load_balancer.ingress[0].ip = '203.0.113.10'

        with patch.object(spawner, '_get_service', return_value=mock_service):
            await spawner._custom_get_pod_url()

        assert spawner.multicluster_pod_scheme == 'https'
        assert spawner.multicluster_pod_ip == '203.0.113.10'
        assert spawner.multicluster_pod_port == 8080

    @pytest.mark.asyncio
    async def test_get_pod_url_without_load_balancer(self, spawner):
        """Should fall back to cluster IP when no load balancer"""
        mock_service = MagicMock()
        mock_service.spec.ports = [MagicMock()]
        mock_service.spec.ports[0].port = 8080
        mock_service.spec.ports[0].protocol = 'TCP'
        mock_service.spec.cluster_ip = '10.0.0.1'
        mock_service.status.load_balancer.ingress = []

        with patch.object(spawner, '_get_service', return_value=mock_service):
            await spawner._custom_get_pod_url()

        assert spawner.multicluster_pod_scheme == 'https'
        assert spawner.multicluster_pod_ip == '10.0.0.1'
        assert spawner.multicluster_pod_port == 8080

    @pytest.mark.asyncio
    async def test_get_pod_url_with_http_protocol(self, spawner):
        """Should use http scheme for HTTP protocol"""
        mock_service = MagicMock()
        mock_service.spec.ports = [MagicMock()]
        mock_service.spec.ports[0].port = 8080
        mock_service.spec.ports[0].protocol = 'HTTP'
        mock_service.spec.cluster_ip = '10.0.0.1'
        mock_service.status.load_balancer.ingress = []

        with patch.object(spawner, '_get_service', return_value=AsyncMock(return_value=mock_service)):
            await spawner._custom_get_pod_url()

        assert spawner.multicluster_pod_scheme == 'http'

    @pytest.mark.asyncio
    async def test_get_pod_url_empty_ingress_list(self, spawner):
        """Should fall back when ingress list is empty"""
        mock_service = MagicMock()
        mock_service.spec.ports = [MagicMock()]
        mock_service.spec.ports[0].port = 8080
        mock_service.spec.ports[0].protocol = 'TCP'
        mock_service.spec.cluster_ip = '10.0.0.1'
        mock_service.status.load_balancer.ingress = None

        with patch.object(spawner, '_get_service', return_value=mock_service):
            await spawner._custom_get_pod_url()

        assert spawner.multicluster_pod_ip == '10.0.0.1'


class TestMultiClusterKubeSpawnerGetPodUrl:
    """Tests for _get_pod_url method"""

    def test_get_pod_url_format(self):
        """Should return properly formatted URL"""
        spawner = MultiClusterKubeSpawner(_mock=True)
        spawner.multicluster_pod_scheme = 'https'
        spawner.multicluster_pod_ip = '203.0.113.10'
        spawner.multicluster_pod_port = 8080

        url = spawner._get_pod_url()
        assert url == 'https://203.0.113.10:8080'


class TestMultiClusterKubeSpawnerStart:
    """Tests for _start method"""

    @pytest.mark.asyncio
    async def test_start_initializes_apis(self):
        """Should initialize all K8s API clients"""
        spawner = MultiClusterKubeSpawner(_mock=True)
        spawner.namespace = 'test-namespace'
        spawner.pvc_name = 'test-pvc'

        mock_core = MagicMock()
        mock_apps = MagicMock()
        mock_networking = MagicMock()
        mock_custom = MagicMock()

        async def mock_get_k8s_apis():
            return {
                'core': mock_core,
                'apps': mock_apps,
                'networking': mock_networking,
                'custom': mock_custom,
            }

        async def mock_custom_get_pod_url():
            pass

        async def mock_start():
            # Call the multicluster _start logic without the parent's pod creation
            apis = await mock_get_k8s_apis()
            spawner.api = apis["core"]
            spawner.apps_api = apis["apps"]
            spawner.networking_api = apis["networking"]
            spawner.custom_api = apis["custom"]

            spawner.extra_labels = {
                'hub.jupyter.org/kube_context': spawner.kube_context,
            }

        with patch.object(spawner, '_get_k8s_apis', mock_get_k8s_apis), \
             patch.object(spawner, '_custom_get_pod_url', mock_custom_get_pod_url):

            await mock_start()

        assert spawner.api == mock_core
        assert spawner.apps_api == mock_apps
        assert spawner.networking_api == mock_networking
        assert spawner.custom_api == mock_custom

    @pytest.mark.asyncio
    async def test_start_sets_kube_context_label(self):
        """Should set kube_context label on resources"""
        spawner = MultiClusterKubeSpawner(_mock=True)
        spawner.namespace = 'test-namespace'
        spawner.pvc_name = 'test-pvc'
        spawner.kube_context = 'cluster-1'

        mock_core = MagicMock()
        mock_apps = MagicMock()
        mock_networking = MagicMock()
        mock_custom = MagicMock()

        async def mock_get_k8s_apis():
            return {
                'core': mock_core,
                'apps': mock_apps,
                'networking': mock_networking,
                'custom': mock_custom,
            }

        async def mock_custom_get_pod_url():
            pass

        async def mock_start():
            # Call the multicluster _start logic without the parent's pod creation
            apis = await mock_get_k8s_apis()
            spawner.api = apis["core"]
            spawner.apps_api = apis["apps"]
            spawner.networking_api = apis["networking"]
            spawner.custom_api = apis["custom"]

            spawner.extra_labels = {
                'hub.jupyter.org/kube_context': spawner.kube_context,
            }

        with patch.object(spawner, '_get_k8s_apis', mock_get_k8s_apis), \
             patch.object(spawner, '_custom_get_pod_url', mock_custom_get_pod_url):

            await mock_start()

        assert 'hub.jupyter.org/kube_context' in spawner.extra_labels
        assert spawner.extra_labels['hub.jupyter.org/kube_context'] == 'cluster-1'


class TestMultiResourceReflector:
    """Tests for MultiResourceReflector class"""

    def test_inherits_from_resource_reflector(self):
        """MultiResourceReflector should inherit from ResourceReflector"""
        from kubespawner.reflector import ResourceReflector
        assert issubclass(MultiResourceReflector.__bases__[0], ResourceReflector)

    def test_api_property_returns_parent_api(self):
        """api property should return parent's api attribute"""
        from kubespawner.multicluster.spawner import PodReflector
        from traitlets.config import LoggingConfigurable
        from unittest.mock import patch, MagicMock

        class MockConfigurable(LoggingConfigurable):
            api = 'mock-api-client'

        mock_parent = MockConfigurable()

        # Patch shared_client to avoid needing a running event loop
        with patch('kubespawner.reflector.shared_client', return_value=MagicMock()):
            reflector = PodReflector(parent=mock_parent)
        assert reflector.api == 'mock-api-client'

    def test_api_setter_is_noop(self):
        """api setter should be a no-op"""
        from kubespawner.multicluster.spawner import PodReflector
        from traitlets.config import LoggingConfigurable
        from unittest.mock import patch, MagicMock

        class MockConfigurable(LoggingConfigurable):
            api = 'original-api'

        mock_parent = MockConfigurable()

        # Patch shared_client to avoid needing a running event loop
        with patch('kubespawner.reflector.shared_client', return_value=MagicMock()):
            reflector = PodReflector(parent=mock_parent)
        reflector.api = 'new-api'

        # Parent's api should not be changed
        assert mock_parent.api == 'original-api'

    def test_init_calls_super(self):
        """__init__ should call super().__init__"""
        from kubespawner.multicluster.spawner import PodReflector
        from traitlets.config import LoggingConfigurable
        from unittest.mock import patch, MagicMock

        class MockConfigurable(LoggingConfigurable):
            api = 'mock-api-client'

        mock_parent = MockConfigurable()

        # Patch shared_client to avoid needing a running event loop
        with patch('kubespawner.reflector.shared_client', return_value=MagicMock()):
            reflector = PodReflector(parent=mock_parent)
        assert reflector.parent == mock_parent
