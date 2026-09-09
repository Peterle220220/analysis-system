# Vo mong. Toan bo logic nam trong tasks.py - khong viet logic o day.
.PHONY: check lint typecheck test web-build run setup clean

check:
	python3 tasks.py check

lint:
	python3 tasks.py lint

typecheck:
	python3 tasks.py typecheck

test:
	python3 tasks.py test

web-build:
	python3 tasks.py web-build

run:
	python3 tasks.py run

setup:
	python3 tasks.py setup

clean:
	python3 tasks.py clean
