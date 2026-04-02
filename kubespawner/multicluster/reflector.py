from ..reflector import ResourceReflector

class MultiResourceReflector(ResourceReflector):
    """
    Base class for multi-cluster resource reflectors.

    This extends ResourceReflector to use the parent spawner's API client
    instead of creating its own via shared_client, enabling per-cluster
    reflectors.
    """

    @property
    def api(self):
        """
        Return the parent spawner's Kubernetes API client.
        """
        return self.parent.api

    @api.setter
    def api(self, value):
        """Setter is a no-op - api is set on the parent."""
        pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
