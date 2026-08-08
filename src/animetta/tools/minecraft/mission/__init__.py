"""Typed adaptive mission contracts and coordination."""

from animetta.tools.minecraft.voyager.goal_models import DiscoverGoal

from .admission import AdmissionContext, AdmissionResult, GoalAdmission
from .models import (
    AutonomyPolicy,
    CheckpointIO,
    EvidenceRef,
    ExecutionPolicy,
    GoalAdmissionDecision,
    GoalProposal,
    MissionObjective,
    MissionReport,
    MissionSpec,
    StageDefinition,
    StageFailure,
    StageIO,
    StageMedia,
    StageStateDelta,
    VerificationPredicate,
    WalkthroughManifest,
)
from .verifier import MissionEvidenceSnapshot, MissionVerificationResult, MissionVerifier

__all__ = [
    "AutonomyPolicy",
    "CheckpointIO",
    "AdmissionContext",
    "AdmissionResult",
    "ExecutionPolicy",
    "EvidenceRef",
    "DiscoverGoal",
    "GoalAdmissionDecision",
    "GoalAdmission",
    "GoalProposal",
    "MissionObjective",
    "MissionReport",
    "MissionSpec",
    "MissionEvidenceSnapshot",
    "MissionVerificationResult",
    "MissionVerifier",
    "StageIO",
    "StageDefinition",
    "StageFailure",
    "StageMedia",
    "StageStateDelta",
    "VerificationPredicate",
    "WalkthroughManifest",
]
