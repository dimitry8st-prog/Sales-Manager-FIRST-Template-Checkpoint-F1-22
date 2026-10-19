"""F1-22 R2 candidate implementation scaffold. Implement CONTRACT.md."""
class TemplateCheckpointError(ValueError):
    @property
    def code(self): return self.args[0]

def capture_checkpoint(loaded_registry, bound_language, *, template_id):
    raise NotImplementedError("F122_R2_IMPLEMENTATION_REQUIRED")

def materialize_checkpoint(blob, *, expected_registry_version, expected_pack_version):
    raise NotImplementedError("F122_R2_IMPLEMENTATION_REQUIRED")

def prepare_checkpoint_materials(blob, loaded_registry, binding_config, *, now,
                                locale, required_template_id, pinned_pack_version,
                                save_materials):
    raise NotImplementedError("F122_R2_IMPLEMENTATION_REQUIRED")
