// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

// Function to apply gradient backgrounds to GPU model columns using model IDs and mapping
async function applyModelGradients() {
    // Load the mapping file
    let response = await fetch('/model_gradient_mapping.json');
    let mapping = await response.json();
    // Map display names to model IDs for lookup
    let displayNameToId = {};
    for (const [id, obj] of Object.entries(mapping)) {
        displayNameToId[obj.display_name] = id;
    }
    // Apply gradients to model columns in the timeline
    const headers = document.querySelectorAll('.timeline-vertical-header');
    headers.forEach(header => {
        const displayName = header.textContent.trim();
        const modelId = displayNameToId[displayName];
        if (modelId && mapping[modelId]) {
            header.style.backgroundImage = `url('${mapping[modelId].gradient}')`;
            header.style.backgroundSize = 'cover';
            header.style.backgroundPosition = 'center';
            header.style.backgroundRepeat = 'no-repeat';
            header.style.color = '#fff'; // White text for better contrast
            header.style.textShadow = '2px 2px 4px rgba(0,0,0,0.8)'; // Text shadow for readability
        }
    });
}

// Call the function when timeline is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Wait a bit for the timeline to render
    setTimeout(applyModelGradients, 1000);
});
