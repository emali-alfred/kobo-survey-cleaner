# Publishing Survey Cleaner on Google Play

The Android app is the web app (`web/`) wrapped as a **Trusted Web Activity**:
a real Play Store app that opens the site full screen, with the Survey Cleaner
icon, and works offline. Updates to the website reach the app automatically,
without publishing a new version.

## 1. Put the web app online (GitHub Pages, free)

1. Merge the branch with the web app into `main`.
2. On GitHub: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. The *Deploy web app* workflow runs on every push to `main`. When it is green,
   the app is live at **https://emali-alfred.github.io/kobo-survey-cleaner/**
4. Open that link on an Android phone in Chrome: the menu offers
   **Install app** already, before the Play Store version exists.

## 2. Make the Android package (PWABuilder, no coding)

1. Go to **https://www.pwabuilder.com**, paste the site address, click *Start*.
2. Click **Package for stores → Android → Generate package**. Suggested settings:
   - Package ID: `io.github.emali_alfred.surveycleaner` (cannot change later)
   - App name: `Survey Cleaner`, launcher name: `Survey Cleaner`
   - Signing key: *Create new*
3. Download the zip. It contains:
   - `*.aab`: the file you upload to Google Play
   - `signing.keystore` and `signing-key-info.txt`: **back these up somewhere
     safe and private** (not in GitHub). Every future update must be signed with
     the same key.
   - `assetlinks.json`: proves to Android that the app and the website belong
     together (see step 3).

## 3. Link the app and the website (removes the browser address bar)

Android looks for the file at the root of the domain,
`https://emali-alfred.github.io/.well-known/assetlinks.json`, which a project
site cannot serve. So:

1. Create a new public GitHub repository named exactly **`emali-alfred.github.io`**.
2. Add two files to it:
   - `.well-known/assetlinks.json`: the file from the PWABuilder zip
   - `.nojekyll`: an empty file (lets GitHub serve the `.well-known` folder)
3. After uploading to Play (step 4), Play Console → **Setup → App signing**
   shows Google's *app signing key* SHA-256 fingerprint. Add it to
   `assetlinks.json` next to the existing one in `sha256_cert_fingerprints`.
   Without this, the Play-installed app shows an address bar at the top.

## 4. Google Play Console

1. Create a developer account at https://play.google.com/console
   (one-time USD 25 fee and identity check).
2. **Create app** → name *Survey Cleaner*, App, Free.
3. Fill in the store listing, privacy policy, data safety and content rating
   with the text in [`listing.md`](listing.md), and upload the graphics:
   - icon: `assets/icon-512-playstore.png`
   - feature graphic: `assets/feature-graphic-1024x500.png`
   - 2 to 8 phone screenshots (take them on your phone)
4. **Testing → Closed testing**: upload the `.aab`. New personal developer
   accounts must run a closed test with at least 12 testers for 14 days before
   they can publish to everyone. Colleagues and enumerators are ideal testers.
5. Then **Production → Create release** with the same `.aab` and submit for review.

## Updating the app later

- Changes to the cleaning code or web page: push to `main`. The site and the
  installed apps update automatically.
- Only a new icon, name or package settings need a new `.aab` (PWABuilder again,
  with the **same signing key**, and a higher version code).
