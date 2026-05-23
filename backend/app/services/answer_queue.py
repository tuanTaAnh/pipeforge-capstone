import asyncio
from typing import List

from app.schemas.runs import AskUserQuestion
from app.services.event_emitter import event_emitter
from app.services.run_registry import registry


class AnswerQueue:
    async def ask_user(
        self,
        run_id: str,
        agent,
        question: str,
        options: List[str],
    ) -> str:
        question_id = f"q_{id(asyncio.current_task())}"

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        pending = AskUserQuestion(
            questionId=question_id,
            question=question,
            options=options,
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

        answer = await future

        registry.runs[run_id]["pendingQuestion"] = None
        registry.runs[run_id]["answerFuture"] = None
        registry.set_status(run_id, "running")

        await event_emitter.emit(
            run_id=run_id,
            event_type="ask_user_answered",
            agent=agent,
            payload={"questionId": question_id, "answer": answer},
        )

        return str(answer)

    def submit_answer(self, run_id: str, question_id: str, answer: str) -> None:
        run = registry.runs[run_id]
        pending = run.get("pendingQuestion")
        future = run.get("answerFuture")

        if not pending or not future:
            raise ValueError("No pending question")

        if pending["questionId"] != question_id:
            raise ValueError("Question ID mismatch")

        if future.done():
            raise ValueError("Question already answered")

        future.set_result(answer)


answer_queue = AnswerQueue()