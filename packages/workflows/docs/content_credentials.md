<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Content credentials

Everything this studio ships is synthetic, and nothing in a frame says so. A C2PA content
credential does: a signed, tamper-evident manifest embedded in the deliverable itself, naming the
generator, the pipeline that produced it, the models it used and the licence it ships under.
Written 2026-10-06. The module is `src/zyg_workflows/provenance_seal.py`; the standard
[C2PA](https://c2pa.org/) specification and the `c2pa-python` library do the signing.

This document is about *file* provenance — who signed this byte stream. For the licence and origin
of the repository's own artefacts and of the weights fetched at run time, see
[PROVENANCE.md](PROVENANCE.md).

## What it proves, and what it does not

A credential that reads back `Valid` and chains to our root proves exactly one thing: **this file
was produced by this installation's signer and has not been modified since.** One flipped byte and
a verifier reports `Invalid`. If the verifier also holds our root certificate, the state is
`Trusted`, which additionally says the signature came from a certificate this studio issued and not
from someone who copied the manifest's shape.

What it deliberately does not prove:

- **Nothing about ownership of the idea.** A credential is a statement about a file, not a
  copyright claim, not an authorship dispute resolved, not a licence grant. The licence named in
  our own assertion is a declaration, not a title deed.
- **Nothing about a file whose credential was stripped.** Re-encoding, a screenshot, a social
  platform's transcoder or `ffmpeg -c copy` all drop the manifest. The absence of a credential
  proves nothing at all — not that the file is fake, not that it is not ours. Only its *presence*
  carries information.
- **Nothing about the content of the frames.** The manifest says a model made this and which
  pipeline ran; it does not certify that what is depicted happened, nor that the result is
  accurate, safe or fit for any purpose.
- **Nothing about files it could not be embedded in.** See "What is not sealed" below.

Trust is a property of the verifier, not of the file. A reader that does not hold our root reports
`Valid` with an untrusted issuer; that is the expected result for a stranger, and the reason the
root is published.

## The flags

Five environment reads, all declared in `src/zyg_workflows/settings.py` and listed with their
defaults in [configuration.md](configuration.md):

| flag | default | what it does |
| --- | --- | --- |
| `ZYG_C2PA` | `warn` | `off` skips sealing entirely; `warn` signs when keys are present and logs and continues when they are not; `strict` raises `SealError` instead of shipping an unsigned deliverable |
| `ZYG_C2PA_KEY` | `~/.config/zygomatic/c2pa/signer.key` | the PKCS#8 ES256 private key of the signer |
| `ZYG_C2PA_CERT_CHAIN` | `~/.config/zygomatic/c2pa/signer_chain.pem` | end-entity certificate **plus** its issuing CA, in that order. A self-signed certificate is refused by the library |
| `ZYG_C2PA_TSA_URL` | *(empty)* | an RFC-3161 timestamp authority; empty means no timestamp. Production sets `http://timestamp.digicert.com` |
| `ZYG_C2PA_ROOT_CERT` | `~/.config/zygomatic/c2pa/root/ca.pem` | the public root, used as a trust anchor when verifying. Only a verifier needs it |

**The key never lives in the repository.** It lives under `~/.config/zygomatic/c2pa` with mode
`0600`, outside every checkout, and no test may read it — the test suite builds its own throwaway
CA in a temporary directory. `warn` is the default precisely so that a fresh checkout with no key
renders normally: the seal is fail-safe, and a missing key, a format the library cannot sign or a
venv without the wheel may never break a render.

## How a deliverable gets sealed

The pipelines call `provenance_seal.seal()` (or `seal_derived()` for a re-encode, which names the
master as a parent ingredient) on the file they are about to hand over. Signing is in place: the
library writes a new file, so the module signs to a temporary file beside the original and
`os.replace`s it over the top — an interrupted seal leaves the original intact, never a
half-written deliverable.

The hooks, by department:

- **Kids series** — the episode mux and the poster.
- **Briefing** — `render_episode`.
- **Documentary** — stage 19, the delivery stage.
- **Video**, **Crime**, **Storyteller** (and the scene service behind it).
- **Remix** and **RemixAI**.
- **Kids music** and **kids video**.
- **Video studio** — the post-process step and the assembly.
- **Voice studio** — every take.
- **Stills** — `char2d`, the contact sheet, picture studio.
- **SFTP egress gate** — nothing leaves by SFTP unsealed.
- **Subburn** — a burned-in-subtitle copy is a re-encode, so it is re-sealed as a derived file.
- **The dashboard and public-site gates** — the last check before a file is offered for download
  or published.

Every hook passes the pipeline name and the run id, and the ones that know them pass the model
list, the prompt ids and the licence, which land in the `org.zygomatic.provenance` assertion
alongside the standard `c2pa.actions`.

### What is not sealed

By design, not by omission:

- **Intermediates.** Scratch renders, frame sequences, pre-mux audio, anything a later stage
  consumes and replaces. Sealing them costs time and proves nothing about what ships.
- **Sidecars.** `.srt`, `.vtt`, `.json`, `.txt`, `.mid` — the format has nowhere to carry a
  manifest. The module skips an unsupported extension instead of treating it as an error.
- **Live transcodes in zero cinema.** Streaming segments are produced on the fly and discarded;
  the sealed master they are made from is the artefact that carries the credential.

## How to verify

Three ways, in increasing order of convenience for an outsider:

1. **`c2patool`**, the reference CLI, with our published root as the trust anchor:

   ```sh
   curl -sO https://<the public site>/.well-known/zygomatic-c2pa-root.pem
   c2patool --trust_anchors zygomatic-c2pa-root.pem episode.mp4
   ```

   Without the anchor the state is `Valid` but the issuer is untrusted; with it, `Trusted`.

2. **The public site's `/verify` page** — upload or point it at a file and it reports the state,
   the issuer, the signing time and our provenance assertion. It holds the root already.

3. **Locally, from this repository:**

   ```sh
   python -m zyg_workflows.provenance_seal verify episode.mp4
   ```

   which prints the full `verify()` dictionary: `sealed`, `state`, `issuer`, `time`, `trusted` and
   the `org.zygomatic.provenance` data. Exit status 0 means a manifest was found.

## Key runbook

### Generate the root and the first signer

Once, on the machine that signs. The root is a CA; the signer is an end-entity certificate issued
by it. A self-signed signer is refused by the library, so there is no shortcut here.

```sh
mkdir -p ~/.config/zygomatic/c2pa/root && cd ~/.config/zygomatic/c2pa/root

# the root: the long-lived CA. Its key is the one secret that must go offline.
openssl ecparam -name prime256v1 -genkey -noout -out ca.key
openssl req -new -x509 -key ca.key -out ca.pem -days 3650 \
  -subj "/CN=Zygomatic C2PA root/O=Zygomatic/C=NL" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

# the signer: an end-entity key (PKCS#8 — a raw "EC PRIVATE KEY" is refused) and a CSR.
cd ~/.config/zygomatic/c2pa
openssl ecparam -name prime256v1 -genkey -noout | openssl pkcs8 -topk8 -nocrypt -out signer.key
openssl req -new -key signer.key -out signer.csr -subj "/CN=Zygomatic signer/O=Zygomatic/C=NL"
printf 'basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=emailProtection\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n' > signer.ext
openssl x509 -req -in signer.csr -CA root/ca.pem -CAkey root/ca.key -CAcreateserial \
  -out signer.pem -days 760 -extfile signer.ext

# the chain the signer uses: end-entity first, then the issuing CA.
cat signer.pem root/ca.pem > signer_chain.pem

chmod 600 signer.key root/ca.key
chmod 644 signer_chain.pem root/ca.pem
rm signer.csr signer.ext
```

Then check it: `python -m zyg_workflows.provenance_seal sign some.png --pipeline test` followed by
`... verify some.png` should report `state: Valid` and `trusted: true`.

### Rotate the signer every two years

Issue a **new end-entity certificate from the same root** — repeat the signer block above into a
fresh `signer.key` / `signer_chain.pem` and replace both files atomically. Nothing else changes:
the root stays the same, so the published anchor stays the same and **files signed with the old
certificate remain valid**. A signature does not expire retroactively; it is checked against the
certificate's validity at signing time, which is why a **timestamp authority is recommended** —
set `ZYG_C2PA_TSA_URL` so each manifest carries a countersigned time and a verifier can establish
that the signing happened while the certificate was current. Keep the retired `signer.pem` in the
key directory for the record; do not delete it.

### Publish the root, keep the CA key offline

The root certificate is **public** and is served by the public site at
`/.well-known/zygomatic-c2pa-root.pem`. Anyone verifying a Zygomatic file needs it and only it.

`root/ca.key` is the opposite: it signs signers, it is never read by a pipeline, and it belongs on
offline media (an encrypted stick in a drawer, not the signing machine's disk). Bring it out for a
rotation and put it back. If it leaks, every credential this studio has ever issued becomes
forgeable and the only remedy is a new root and a re-publication — which is the whole reason the
day-to-day signing key is a separate, short-lived, replaceable end-entity key.
