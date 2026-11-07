.PHONY: demo test
demo:
	python demo.py
test:
	python -m pytest -q
