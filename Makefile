.PHONY: doctor dev test demo-reset eval

doctor:
	./scripts/doctor.sh

dev:
	./scripts/dev.sh

test:
	./scripts/test.sh

demo-reset:
	./scripts/demo_reset.sh

eval:
	./scripts/eval_baseline.sh
