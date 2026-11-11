Doc-ID: HL-POL-014
Title: Security Baseline
Source: Synthetic policy written for this demo. Helios Ledger Ltd is a fictional company.
License: CC0-1.0

# Security Baseline

This baseline is the fictional security rule for Helios Ledger production systems. It is demo text.

## Clause 1.2 Production databases

Production databases are encrypted at rest with AES-256 and access requires SSO plus a hardware key. A password alone does not open a production database.

## Clause 2.4 Leavers

Admin access is removed on the day an engagement ends. The people system sends the removal ticket to the security queue.

## Clause 3.1 Backups

Backups of production databases are stored in the EEA hosting region. A backup stored outside that region has to follow the transfer policy.
