from ..reflector import ResourceReflector

class MultiResourceReflector(ResourceReflector):

  @property
  def api(self):
    return self.parent.api

  @api.setter
  def api(self, value):
    pass

  # @property
  # def user_options(self):
  #   return self.parent.user_options

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
