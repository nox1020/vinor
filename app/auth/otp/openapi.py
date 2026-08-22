# -*- coding: utf-8 -*-
"""OpenAPI fragment for /auth OTP endpoints (project has no Swagger UI)."""

OPENAPI = {
    "openapi": "3.0.3",
    "info": {
        "title": "Vinor Auth OTP",
        "version": "1.0.0",
        "description": "Additive OTP API. Existing /express/partner login routes are unchanged.",
    },
    "paths": {
        "/auth/request-otp": {
            "post": {
                "summary": "Request a one-time login code",
                "description": (
                    "Unauthenticated. Canonical phone 09xxxxxxxxx. "
                    "Rate limits: 1/60s/phone, 5/hour/phone, 20/hour/IP. "
                    "Does not reveal whether the user exists. Never returns OTP in production."
                ),
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["phone"],
                                "properties": {
                                    "phone": {
                                        "type": "string",
                                        "example": "09121234567",
                                    }
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Accepted (generic success copy)",
                    },
                    "400": {"description": "OTP_INVALID_PHONE"},
                    "429": {"description": "OTP_RATE_LIMITED or OTP_COOLDOWN"},
                },
            }
        },
        "/auth/verify-otp": {
            "post": {
                "summary": "Verify OTP and create partner session cookie",
                "description": (
                    "Creates the existing Flask session (vinor_session). "
                    "Max 5 attempts per challenge. OTP is single-use."
                ),
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["phone", "code"],
                                "properties": {
                                    "phone": {"type": "string", "example": "09121234567"},
                                    "code": {"type": "string", "example": "58321"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Authenticated; session cookie set"},
                    "400": {
                        "description": "OTP_INVALID / OTP_EXPIRED / OTP_ALREADY_USED / OTP_INVALID_PHONE"
                    },
                    "429": {"description": "OTP_TOO_MANY_ATTEMPTS"},
                },
            }
        },
    },
}
