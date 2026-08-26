from application.training_sessions.dto import TrainingGroupWithoutTrainer


class InvalidGenerationWindowError(Exception):
    pass


class MissingTrainingGroupTrainersError(Exception):
    def __init__(
        self,
        training_groups: tuple[TrainingGroupWithoutTrainer, ...],
    ) -> None:
        super().__init__("Training groups must have trainers before generation")
        self.training_groups = training_groups
