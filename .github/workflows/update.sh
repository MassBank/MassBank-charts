#!/bin/bash

update_chart_file() {
    file=$1
    version=$2
    echo "Updating chart file: $file"
    echo " -> Input version string: $version"   

    # Remove leading 'v' if present
    mod_version=${version#v}
    # Copy IFS and change it temporarily
    IFS_orig=$IFS
    # Set IFS to dot for splitting
    IFS='.' 
    # Read version into an array
    read -r major minor patch <<< "$mod_version"
    # Restore IFS for next use
    IFS=$IFS_orig
    helm_version=$(grep '^version' "$file" | awk '{print $2}')    
    # Read Helm version into an array
    # Set IFS to dot for splitting
    IFS='.'
    read -r major_helm minor_helm patch_helm <<< "$helm_version"

    if [ $major != $major_helm ] && [ $major -ge $major_helm ]; then
        major_helm=$major
        minor_helm=$minor
        patch_helm=0
    elif [ $minor_helm != $minor ] && [ $minor -ge $minor_helm ]; then
        minor_helm=$minor
        patch_helm=0
    else
        patch_helm=$((patch_helm + 1))
    fi

    helm_version="$major_helm.$minor_helm.$patch_helm"
    sed "s/^version: .*/version: $helm_version/g" "$file" > "${file}_mod.yaml"
    sed "s/^appVersion: .*/appVersion: \"$version\"/g" "${file}_mod.yaml" > "${file}_mod_2.yaml"    
    mv "${file}_mod_2.yaml" "$file"
    rm "${file}_mod.yaml"

    echo " -> Chart file update complete for $file"

    # Restore IFS
    IFS=$IFS_orig
}

version=$1
# update api
echo "Updating MassBank-api version..."
update_chart_file "charts/massbank-api/Chart.yaml" "$version"
echo "MassBank-api version updates complete"
# update frontend 
echo "Updating MassBank-frontend version..."
update_chart_file "charts/massbank-frontend/Chart.yaml" "$version"
echo "MassBank-frontend version update complete"
# update dbtool
echo "Updating MassBank-dbtool version..."
update_chart_file "charts/massbank-dbtool/Chart.yaml" "$version"
echo "MassBank-dbtool version update complete"

echo " -> Version updates complete"