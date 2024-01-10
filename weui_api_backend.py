import bpy
from bpy.props import FloatProperty, IntProperty, EnumProperty, BoolProperty
from typing import List, Tuple
from dream_textures.api import *
from .preferences import StableDiffusionPreferences
import requests
import urllib.parse

svr_url = ""
session = requests.Session()
sd_models = []


class WebUIApiBackend(Backend):
    name = "SD WebUI API"
    description = "A short description of this backend"

    custom_optimization: bpy.props.BoolProperty(name="My Custom Optimization")

    def _get_url(self, path: str) -> str:
        return urllib.parse.urljoin(svr_url, path)

    def list_models(self, context) -> List[Model]:
        if len(sd_models) > 0:
            return sd_models

        global svr_url
        svr_url = context.preferences.addons[StableDiffusionPreferences.bl_idname].preferences.server_url
        model_data = session.get(self._get_url("/sdapi/v1/sd-models"))
        print(self._get_url("/sdapi/v1/sd-models"), model_data)
        for m in model_data.json():
            sd_models.append(Model(name=m["model_name"], description=m["filename"], id=m["title"]))

        for m in sd_models:
            print(m)
        return sd_models

    def list_schedulers(self, context) -> List[str]:
        return ["remote"]

    def generate(self, arguments: GenerationArguments, step_callback: StepCallback, callback: Callback):
        print(arguments)
        callback(NotImplementedError("This backend is not implemented yet"))

    def draw_speed_optimizations(self, layout, context):
        layout.prop(self, "custom_optimization")
