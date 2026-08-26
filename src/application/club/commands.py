from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AssignTrainingGroupTrainerCommand:
    actor_telegram_id: int
    training_group_id: int
    trainer_user_id: int
