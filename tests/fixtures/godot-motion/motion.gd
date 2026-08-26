extends Node2D

const FRAME_LIMIT: int = 24
const START_X: float = 24.0
const STEP_X: float = 11.0

var _frame: int = 0


func _ready() -> void:
	queue_redraw()


func _process(_delta: float) -> void:
	_frame += 1
	queue_redraw()
	if _frame >= FRAME_LIMIT:
		get_tree().quit()


func _draw() -> void:
	draw_circle(Vector2(160.0, 90.0), 62.0, Color(0.08, 0.13, 0.22, 1.0))
	var travel_frame: int = min(_frame, FRAME_LIMIT - 1)
	var x_position: float = START_X + STEP_X * float(travel_frame)
	draw_rect(Rect2(Vector2(x_position, 78.0), Vector2(22.0, 22.0)), Color(0.25, 0.93, 0.75, 1.0), true)
	draw_line(Vector2(18.0, 111.0), Vector2(302.0, 111.0), Color(0.48, 0.61, 0.82, 1.0), 2.0)
