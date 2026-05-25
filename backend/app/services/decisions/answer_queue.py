import json

import asyncio
from typing import Any

from app.schemas.runs import AskUserOption, AskUserQuestion
from app.services.runtime.event_emitter import event_emitter
from app.services.runtime.run_registry import registry


class AnswerQueue:
    async def ask_user_decision(
        self,
        run_id: str,
        agent,
        question: dict[str, Any],
        validation_error: str | None = None,
    ) -> dict[str, Any]:
        question_id = question["id"]

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        options = [
            AskUserOption(
                id=option["id"],
                label=option["label"],
                resolved_rule=option.get("resolved_rule"),
                implementation=option.get("implementation"),
            )
            for option in question.get("options", [])
        ]

        pending = AskUserQuestion(
            questionId=question_id,
            question=question["question"],
            options=options,
            issueSummary=question.get("issue_summary"),
            priority=question.get("priority", "must_answer"),
            recommendedOptionId=question.get("recommended_option_id"),
            recommendationReason=question.get("recommendation_reason"),
            allowCustomAnswer=question.get("allow_custom_answer", True),
            validationError=validation_error,
        )

        print(
            "[PF DEBUG][answer_queue][pending_question]",
            json.dumps(pending.model_dump(), ensure_ascii=False, default=str, indent=2),
            flush=True,
        )

        registry.runs[run_id]["pendingQuestion"] = pending.model_dump()
        registry.runs[run_id]["answerFuture"] = future
        registry.set_status(run_id, "waiting_for_user")

        await event_emitter.emit(
            run_id=run_id,
            event_type="ask_user",
            agent=agent,
            payload=pending.model_dump(),
        )

        answer_payload = await future

        registry.runs[run_id]["pendingQuestion"] = None
        registry.runs[run_id]["answerFuture"] = None
        registry.set_status(run_id, "running")

        await event_emitter.emit(
            run_id=run_id,
            event_type="ask_user_answered",
            agent=agent,
            payload={
                "questionId": question_id,
                "answer": _display_answer(answer_payload),
                "answerPayload": answer_payload,
            },
        )

        return answer_payload

    def submit_answer(
        self,
        run_id: str,
        question_id: str,
        answer: dict[str, Any] | str,
    ) -> None:
        run = registry.runs[run_id]
        pending = run.get("pendingQuestion")
        future = run.get("answerFuture")

        if not pending or not future:
            raise ValueError("No pending question")

        if pending["questionId"] != question_id:
            raise ValueError("Question ID mismatch")

        if future.done():
            raise ValueError("Question already answered")

        if isinstance(answer, str):
            payload = {"questionId": question_id, "answer": answer, "customAnswer": answer}
        else:
            payload = dict(answer)
            payload["questionId"] = question_id

        print(
            "[PF DEBUG][answer_queue][submit_answer]",
            json.dumps(
                {
                    "run_id": run_id,
                    "question_id": question_id,
                    "pending": pending,
                    "payload": payload,
                },
                ensure_ascii=False,
                default=str,
                indent=2,
            ),
            flush=True,
        )

        future.set_result(payload)


def _display_answer(answer_payload: dict[str, Any]) -> str:
    return str(
        answer_payload.get("answer")
        or answer_payload.get("customAnswer")
        or answer_payload.get("selectedOptionId")
        or ""
    )


answer_queue = AnswerQueue()