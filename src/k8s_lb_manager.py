#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
"""KubernetesLoadBalancer Controller."""

import logging
import re
from typing import Dict, List, Optional

from lightkube import ApiError, Client
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Service
from lightkube.types import PatchType

logger = logging.getLogger(__name__)

# Regex for Kubernetes annotation values:
# - Allows alphanumeric characters, dots (.), dashes (-), and underscores (_)
# - Matches the entire string
# - Does not allow empty strings
# - Example valid: "value1", "my-value", "value.name", "value_name"
# - Example invalid: "value@", "value#", "value space"
ANNOTATION_VALUE_PATTERN = re.compile(r"^[\w.\-_]+$")

# Based on https://github.com/kubernetes/apimachinery/blob/v0.31.3/pkg/util/validation/validation.go#L204
# Regex for DNS1123 subdomains:
# - Starts with a lowercase letter or number ([a-z0-9])
# - May contain dashes (-), but not consecutively, and must not start or end with them
# - Segments can be separated by dots (.)
# - Example valid: "example.com", "my-app.io", "sub.domain"
# - Example invalid: "-example.com", "example..com", "example-.com"
DNS1123_SUBDOMAIN_PATTERN = re.compile(
    r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$"
)

# Based on https://github.com/kubernetes/apimachinery/blob/v0.31.3/pkg/util/validation/validation.go#L32
# Regex for Kubernetes qualified names:
# - Starts with an alphanumeric character ([A-Za-z0-9])
# - Can include dashes (-), underscores (_), dots (.), or alphanumeric characters in the middle
# - Ends with an alphanumeric character
# - Must not be empty
# - Example valid: "annotation", "my.annotation", "annotation-name"
# - Example invalid: ".annotation", "annotation.", "-annotation", "annotation@key"
QUALIFIED_NAME_PATTERN = re.compile(r"^[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?$")


class KubernetesLoadBalancer:
    """KubernetesLoadBalancer."""

    def __init__(
        self,
        name: str,
        namespace: str,
        field_manager: str,
        ports: List[ServicePort],
        additional_labels: Optional[Dict[str, str]] = None,
        additional_selectors: Optional[Dict[str, str]] = None,
        additional_annotations: Optional[str] = None,
    ):
        """Initialize the KubernetesLoadBalancer.

        :param name: Name of the LoadBalancer.
        :param namespace: Namespace for the LoadBalancer.
        :param ports: List of ServicePort objects.
        :param additional_labels: Additional labels to apply.
        :param additional_selectors: Additional selectors to match pods.
        :param additional_annotations: Additional annotations to apply.
        """
        self.name = name
        self.namespace = namespace
        self.ports = ports
        self.field_manager = field_manager
        self.additional_labels = additional_labels or {}
        self.additional_selectors = additional_selectors or {}
        self.additional_annotations = additional_annotations or {}
        self.additional_annotations = parse_annotations(additional_annotations)
        # Initialize Kubernetes client
        self.client = Client(namespace=self.namespace, field_manager=self.field_manager)

        if self._annotations_valid():
            self.reconcile()
        else:
            self.remove_lb()

    def remove_lb(self):
        """Removes the LoadBalancer."""
        try:
            self.client.delete(Service, name=self.name, namespace=self.namespace)
            logger.info(f"Deleted LoadBalancer {self.name} in namespace {self.namespace}")
        except ApiError as e:
            logger.info(f"Failed to delete LoadBalancer {self.name}: {e}")

    def reconcile(self):
        """Reconcile the LoadBalancer's state."""
        # Desired state of the LoadBalancer
        service = Service(
            metadata=ObjectMeta(
                name=self.name,
                namespace=self.namespace,
                labels=self.additional_labels,
                annotations=self.additional_annotations,
            ),
            spec=ServiceSpec(
                ports=self.ports,
                selector=self.additional_selectors,
                type="LoadBalancer",
            ),
        )

        try:
            # Check if the service exists
            existing_service = self.client.get(Service, name=self.name, namespace=self.namespace)

            # Patch if differences exist
            if not self._is_patched(old_service=existing_service, new_service=service):
                self.client.patch(Service, name=self.name, obj=service, patch_type=PatchType.APPLY)
                logger.info(f"Patched LoadBalancer {self.name} in namespace {self.namespace}")
            else:
                logger.debug(f"No changes for LoadBalancer {self.name}")
        except ApiError as e:
            # Create the service if it doesn't exist
            if e.status.code == 404:
                self.client.create(service)
                logger.info(f"Created LoadBalancer {self.name} in namespace {self.namespace}")
            else:
                logger.info(f"Failed to create LoadBalancer {self.name}: {e}")

    def _is_patched(self, old_service: Service, new_service: Service) -> bool:
        """Reports if the service has already been patched.

        Returns:
            bool: A boolean indicating if the service patch has been applied.
        """
        new_ports = [(p.port, p.targetPort) for p in new_service.spec.ports]  # type: ignore[attr-defined]
        old_ports = [
            (p.port, p.targetPort) for p in old_service.spec.ports  # type: ignore[attr-defined]
        ]
        ports_match = new_ports == old_ports

        new_annotations = (
            new_service.metadata.annotations or {}  # pyright: ignore[reportOptionalMemberAccess]
        )
        old_annotations = (
            old_service.metadata.annotations or {}  # pyright: ignore[reportOptionalMemberAccess]
        )
        annotations_match = new_annotations == old_annotations

        return ports_match and annotations_match

    def _annotations_valid(self) -> bool:
        """Check if the annotations are valid.

        :return: True if the annotations are valid, False otherwise.
        """
        if self.additional_annotations is None:
            logger.error("Annotations are invalid or could not be parsed.")
            return False
        return True


def validate_annotation_key(key: str) -> bool:
    """Validate the annotation key."""
    if len(key) > 253:
        logger.error(f"Invalid annotation key: '{key}'. Key length exceeds 253 characters.")
        return False

    if not is_qualified_name(key.lower()):
        logger.error(f"Invalid annotation key: '{key}'. Must follow Kubernetes annotation syntax.")
        return False

    if key.startswith(("kubernetes.io/", "k8s.io/")):
        logger.error(f"Invalid annotation: Key '{key}' uses a reserved prefix.")
        return False

    return True


def validate_annotation_value(value: str) -> bool:
    """Validate the annotation value."""
    if not ANNOTATION_VALUE_PATTERN.match(value):
        logger.error(
            f"Invalid annotation value: '{value}'. Must follow Kubernetes annotation syntax."
        )
        return False

    return True


def parse_annotations(annotations: Optional[str]) -> Optional[Dict[str, str]]:
    """Parse and validate annotations from a string.

    logic is based on Kubernetes annotation validation as described here:
    https://github.com/kubernetes/apimachinery/blob/v0.31.3/pkg/api/validation/objectmeta.go#L44
    """
    if not annotations:
        return {}

    annotations = annotations.strip().rstrip(",")  # Trim spaces and trailing commas

    try:
        parsed_annotations = {
            key.strip(): value.strip()
            for key, value in (pair.split("=", 1) for pair in annotations.split(",") if pair)
        }
    except ValueError:
        logger.error(
            "Invalid format for 'loadbalancer_annotations'. "
            "Expected format: key1=value1,key2=value2."
        )
        return None

    # Validate each key-value pair
    for key, value in parsed_annotations.items():
        if not validate_annotation_key(key) or not validate_annotation_value(value):
            return None

    return parsed_annotations


def is_qualified_name(value: str) -> bool:
    """Check if a value is a valid Kubernetes qualified name."""
    parts = value.split("/")
    if len(parts) > 2:
        return False  # Invalid if more than one '/'

    if len(parts) == 2:  # If prefixed
        prefix, name = parts
        if not prefix or not DNS1123_SUBDOMAIN_PATTERN.match(prefix):
            return False
    else:
        name = parts[0]  # No prefix

    if not name or len(name) > 63 or not QUALIFIED_NAME_PATTERN.match(name):
        return False

    return True
