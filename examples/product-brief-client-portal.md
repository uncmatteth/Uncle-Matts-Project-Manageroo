# Client portal

## What I want

Build a client portal where a client can sign in, view only their own projects, upload documents, see project status history, receive notifications, and message our team.

## Who it is for

Existing customers and the internal team serving them.

## Required outcomes

- A client cannot access another client's data.
- Uploads are associated with the correct project.
- Status history is chronological and understandable.
- Messages appear for the client and internal team.
- The existing admin workflow continues to work.
- A real browser demonstration proves one successful client journey and one rejected cross-client access attempt.

## Must not happen

- Do not replace the current authentication provider.
- Do not expose internal-only notes.
- Do not introduce a second UI component system.
- Do not invent a custom file-storage service when the existing provider is suitable.

## Existing product

There is an admin application and existing customer/project data. Preserve it.

## Ideas that may belong later

- Estimate approvals
- Client billing history
- Mobile push notifications
