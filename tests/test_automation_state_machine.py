import unittest

from energy_research_agent.automation.state_machine import (
    LEGAL_TRANSITIONS,
    TERMINAL_STATES,
    InvalidTransitionError,
    TaskStateMachine,
    assert_transition,
    is_terminal,
)
from energy_research_agent.automation.enums import TaskStatus


class TestTaskStateMachine(unittest.TestCase):
    def test_happy_path_reaches_published(self):
        machine = TaskStateMachine()
        for target in (
            TaskStatus.QUEUED,
            TaskStatus.RESEARCHING,
            TaskStatus.EVIDENCE_COLLECTED,
            TaskStatus.VALIDATING,
            TaskStatus.REVIEW_REQUIRED,
            TaskStatus.APPROVED,
            TaskStatus.FROZEN,
            TaskStatus.PUBLISHING,
            TaskStatus.PUBLISHED,
        ):
            machine.transition(target)
        self.assertEqual(machine.state, TaskStatus.PUBLISHED)
        self.assertEqual(len(machine.history), 9)

    def test_auto_pass_path_skips_review(self):
        machine = TaskStateMachine()
        for target in (
            TaskStatus.QUEUED,
            TaskStatus.RESEARCHING,
            TaskStatus.EVIDENCE_COLLECTED,
            TaskStatus.VALIDATING,
            TaskStatus.APPROVED,
            TaskStatus.FROZEN,
            TaskStatus.PUBLISHING,
            TaskStatus.PUBLISHED,
        ):
            machine.transition(target)
        self.assertEqual(machine.state, TaskStatus.PUBLISHED)

    def test_validating_cannot_jump_to_published(self):
        machine = TaskStateMachine()
        for target in (
            TaskStatus.QUEUED,
            TaskStatus.RESEARCHING,
            TaskStatus.EVIDENCE_COLLECTED,
            TaskStatus.VALIDATING,
        ):
            machine.transition(target)
        self.assertFalse(machine.can_transition(TaskStatus.PUBLISHED))
        with self.assertRaises(InvalidTransitionError):
            machine.transition(TaskStatus.PUBLISHED)
        # state unchanged after rejected transition
        self.assertEqual(machine.state, TaskStatus.VALIDATING)

    def test_validating_allowed_targets_are_exact(self):
        self.assertEqual(
            LEGAL_TRANSITIONS[TaskStatus.VALIDATING],
            frozenset({TaskStatus.REVIEW_REQUIRED, TaskStatus.APPROVED, TaskStatus.BLOCKED}),
        )

    def test_terminal_states_reject_everything(self):
        for status in TERMINAL_STATES:
            machine = TaskStateMachine(initial=status)
            self.assertTrue(is_terminal(status))
            for target in TaskStatus:
                self.assertFalse(machine.can_transition(target))
                with self.assertRaises(InvalidTransitionError):
                    machine.transition(target)

    def test_failed_only_retries(self):
        machine = TaskStateMachine(initial=TaskStatus.FAILED)
        self.assertEqual(LEGAL_TRANSITIONS[TaskStatus.FAILED], frozenset({TaskStatus.RETRYING}))
        with self.assertRaises(InvalidTransitionError):
            machine.transition(TaskStatus.RESEARCHING)
        machine.transition(TaskStatus.RETRYING, reason="retry 1/3")
        self.assertEqual(machine.state, TaskStatus.RETRYING)

    def test_review_rejection_path(self):
        machine = TaskStateMachine(initial=TaskStatus.REVIEW_REQUIRED)
        machine.transition(TaskStatus.REJECTED, reason="reviewer rejected")
        self.assertTrue(is_terminal(machine.state))

    def test_transition_history_records_reason(self):
        machine = TaskStateMachine()
        machine.transition(TaskStatus.QUEUED, reason="task accepted")
        record = machine.history[0]
        self.assertEqual(record.from_status, TaskStatus.CREATED)
        self.assertEqual(record.to_status, TaskStatus.QUEUED)
        self.assertEqual(record.reason, "task accepted")
        self.assertIsNotNone(record.at)

    def test_assert_transition_pure_function(self):
        assert_transition(TaskStatus.APPROVED, TaskStatus.FROZEN)
        with self.assertRaises(InvalidTransitionError) as ctx:
            assert_transition(TaskStatus.FROZEN, TaskStatus.PUBLISHED)
        self.assertEqual(ctx.exception.source, TaskStatus.FROZEN)
        self.assertEqual(ctx.exception.target, TaskStatus.PUBLISHED)

    def test_every_status_declares_its_transitions(self):
        self.assertEqual(set(LEGAL_TRANSITIONS), set(TaskStatus))


if __name__ == "__main__":
    unittest.main()
