extends Node


func _ready() -> void:
	push_error("MADO_RUNTIME_FIXTURE")
	get_tree().quit(1)
