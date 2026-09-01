# MemoIsle Design System

## 1. Brand Direction

MemoIsle is a calm, private place for useful fragments: words, resources, and ideas. The “isle” metaphor should appear through generous space, soft layered surfaces, and restrained teal accents. Do not use literal tropical illustrations, glossy gradients, or gamified streak visuals.

Design keywords: calm, trustworthy, focused, personal, tactile, clear.

## 2. Color

Light mode is the MVP default.

- Primary / Deep Teal: `#177A72`
- Primary Hover: `#0F625C`
- Primary Soft: `#E2F2EE`
- Accent / Warm Amber: `#E69A45`
- Background / Warm Mist: `#F6F7F2`
- Surface: `#FFFFFF`
- Surface Subtle: `#EEF2EF`
- Text Strong: `#1E2B29`
- Text Muted: `#687673`
- Border: `#DCE4E0`
- Success: `#2E7D5A`
- Warning: `#B36A1E`
- Danger: `#B84A4A`
- Focus Ring: `#63B8AE`

Use teal for primary actions and active navigation. Use amber sparingly for reminders or a single highlighted insight. Type identity should also use icon and label, never color alone.

## 3. Typography

- Headline: Sora, fallback to Noto Sans SC and system sans-serif.
- Body and UI: Inter, fallback to Noto Sans SC and system sans-serif.
- Page title: 28/36, weight 650.
- Section title: 20/28, weight 650.
- Card title: 16/24, weight 600.
- Body: 15/24, weight 400.
- Label: 13/18, weight 550.
- Metadata: 12/18, weight 450.

Use sentence case. Avoid oversized marketing typography inside the product workspace.

## 4. Shape, Spacing, and Elevation

- Base spacing unit: 4 px.
- Common gaps: 8, 12, 16, 24, 32 px.
- Input and button radius: 10 px.
- Card and panel radius: 14 px.
- Pill and filter chip radius: full.
- Controls: 40 px minimum on Web, 44 dp minimum on Android.
- Cards use a 1 px border and little or no shadow.
- Floating drawers and menus use a soft shadow with low opacity.

The interface should feel structured through alignment and whitespace, not through many nested cards.

## 5. Icons and Content Type Identity

Use rounded line icons with consistent 1.75–2 px strokes.

- Word: `Aa` or book-open icon, teal soft background.
- Resource: link or bookmark icon, blue-gray soft background.
- Idea: spark or bulb icon, amber soft background.
- Voice: microphone icon, warm red recording state only while active.

Always pair unfamiliar icons with labels or accessible names.

## 6. Core Components

### Navigation

- Web: 232 px left rail with logo, primary routes, collections, and account/sync status at the bottom.
- Android: four-item bottom navigation for Home, Library, Review, and Me, plus a prominent create action.
- Active items use a soft teal container and strong text, not a thin color-only indicator.

### Global Search

- Large enough to be a primary tool but not a hero banner.
- Shows shortcut hint on Web and filter entry on Android.
- Results include type, title, matched excerpt, tags, and source/time metadata.

### Quick Capture

- Looks like an inviting composer, with placeholder “Save a word, link, or thought…”.
- Supports type switch, text/URL input, microphone, and one clear Save action.
- Advanced metadata stays collapsed until requested.
- Typing `@` in Web capture opens a command menu; `@网页` lists the currently open HTTP(S) pages from the connected Chrome browser and renders the selected page as an attachment card rather than plain text.

### Memo Row

- Left: type icon.
- Center: title, one or two excerpt lines, compact tags and source.
- Right: updated time and one contextual action.
- Hover actions appear on Web; primary actions remain discoverable without hover on Android.

### Review Card

- One focal item at a time.
- Clear progress and a quiet “Show answer” action.
- Feedback buttons include text labels: Forgot, Unsure, Remembered.

### Voice Recorder

- Real audio-level feedback, elapsed time, pause/resume, finish, and cancel.
- Recording state uses a small red signal but keeps the overall warm-light surface.
- Clearly explain that transcription begins after saving.

## 7. Layout

### Desktop Web — 1440×1024 Reference

- Fixed left navigation: 232 px.
- Main content max width: 920 px.
- Optional right context column: 240 px, hidden below 1180 px.
- Page padding: 32 px desktop, 24 px compact.
- Content rhythm: header, quick capture, review block, recent list.

### Android — 412×915 Reference

- Respect system status, navigation, gesture, keyboard, and cutout insets.
- Horizontal page padding: 16 dp.
- Section gap: 24 dp.
- Use a single-column content flow.
- Bottom navigation must not overlap the create action or scrolling content.

## 8. Key Screen Specifications

### W-01 Web Home / Library Workspace

Create a production app workspace, not a landing page. Include a left navigation rail, a top global search, a primary New button, a compact quick-capture composer, a Today’s Review card, three small queue counts, and a mixed recent memo list. Show realistic Chinese interface copy with English word examples. Include Word, Resource, and Idea rows with clear type identity. Add a subtle sync-complete status near the user profile.

### W-02 Web Quick Capture Drawer

Show the W-01 workspace dimmed behind a 480 px right drawer. The drawer has segmented types 单词 / 资料 / 灵感, a large content field, URL or source preview when relevant, microphone action, collapsed “补充信息”, tags, and a fixed footer with Cancel and Save. Use a realistic pasted learning-resource URL. Show the selected Resource state.

### A-01 Android Home

Create an Android app home screen with a compact header, sync status, Today’s Review card, three quick actions for words, ideas, and voice, and recent mixed content. Web resources in the mixed list open a read-only detail with a prominent source link. Use the four-item bottom navigation and a prominent create action. The screen must remain useful at 360 dp width and with larger text.

### A-03 Android Voice Idea Recorder

Create a focused voice capture screen titled 语音灵感. Show elapsed time, real input-level bars or waveform, recording status, pause/resume, Finish, and Cancel. Include text explaining that the original recording is saved and transcription starts after completion. Keep controls reachable with one hand and include a visible microphone-permission fallback note area.

### A-07 Android Word Review

Create a focused review screen with progress 3/12, the word “serendipity”, pronunciation button, a saved context sentence, and a Show Answer action. Also show the expanded answer state in the same visual direction if the generator supports a state example: Chinese meaning, another example, and Forgot / Unsure / Remembered actions.

## 9. Required States

Every major screen family must define:

- Loading with stable skeleton layout.
- Empty state with one relevant action.
- Offline or waiting-to-sync state.
- Recoverable error with Retry.
- Disabled and permission-denied states.
- Long title, long URL, multiple tags, and large-font behavior.

## 10. Accessibility

- Meet WCAG AA contrast for text and controls.
- Use 44×44 minimum touch targets.
- Provide visible keyboard focus on Web.
- Do not rely on color, waveform, or icon alone for meaning.
- Support reduced motion and system font scaling.
- Keep destructive actions visually separated from primary actions.

## 11. Avoid

- Marketing landing-page layouts inside authenticated product screens.
- Excessive gradients, glassmorphism, neon glows, or decorative blobs.
- Dense dashboard charts unrelated to capture and recall.
- Three separate visual systems for words, resources, and ideas.
- Low-contrast gray-on-gray text.
- Floating actions that cover content or Android gesture areas.
