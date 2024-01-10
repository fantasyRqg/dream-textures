import bpy
from bpy.props import FloatProperty, IntProperty, EnumProperty, BoolProperty
from typing import List, Tuple
from dream_textures.api import *
import requests


class WebUIApiBackend(Backend):
    name = "SD WebUI API"
    description = "A short description of this backend"

    custom_optimization: bpy.props.BoolProperty(name="My Custom Optimization")
    url: bpy.props.StringProperty(name="URL")

    session = requests.Session()

    def _get_url(self, path: str) -> str:
        return f"{self.url}/{path}"

    def list_models(self, context) -> List[Model]:
        model_data = self.session.get(self._get_url("/sdapi/v1/sd-models"))
        models = []
        for model in model_data.json():
            models.append(Model(model["model_name"], model["filename"], model["hash"]))
        return models

    def list_schedulers(self, context) -> List[str]:
        return ["remote"]

    def generate(self, arguments: GenerationArguments, step_callback: StepCallback, callback: Callback):
        print(arguments)
        callback(NotImplementedError("This backend is not implemented yet"))

    def draw_speed_optimizations(self, layout, context):
        layout.prop(self, "custom_optimization")
