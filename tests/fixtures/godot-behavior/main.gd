extends Node

@onready var status: Label = $Status
var activation_count: int = 0

func _ready() -> void:
	print("[MADO_P3] state=READY count=0")

func _process(_delta: float) -> void:
	if Input.is_action_just_pressed("activate"):
		activation_count += 1
		status.text = "ACTIVATED"
		print("[MADO_P3] state=ACTIVATED count=%d" % activation_count)
