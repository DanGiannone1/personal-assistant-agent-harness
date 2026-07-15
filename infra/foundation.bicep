targetScope = 'subscription'

@description('The new, isolated MVP resource group.')
param resourceGroupName string = 'csa-workbench-rg'
param location string = 'eastus'
param environmentName string = 'csa-workbench-env'
param cosmosAccountName string = 'csaworkbench9fc05183'
param storageAccountName string = 'csaworkbench9fc05183'
param sharedAcrName string = 'djgsharedacr'
param sharedAcrResourceGroup string = 'shared-services-rg'
param azureOpenAiName string = 'rfpagent-ai'
param azureOpenAiResourceGroup string = 'flow-dev-rg'

resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
}

module platform 'platform.bicep' = {
  name: 'platform'
  scope: resourceGroup
  params: {
    location: location
    environmentName: environmentName
    cosmosAccountName: cosmosAccountName
    storageAccountName: storageAccountName
    sharedAcrName: sharedAcrName
    sharedAcrResourceGroup: sharedAcrResourceGroup
    azureOpenAiName: azureOpenAiName
    azureOpenAiResourceGroup: azureOpenAiResourceGroup
  }
}

output environmentDefaultDomain string = platform.outputs.environmentDefaultDomain
output environmentId string = platform.outputs.environmentId
output cosmosAccountName string = platform.outputs.cosmosAccountName
output cosmosEndpoint string = platform.outputs.cosmosEndpoint
output storageAccountName string = platform.outputs.storageAccountName
output storageBlobEndpoint string = platform.outputs.storageBlobEndpoint
output frontendIdentityId string = platform.outputs.frontendIdentityId
output frontendIdentityClientId string = platform.outputs.frontendIdentityClientId
output frontendIdentityPrincipalId string = platform.outputs.frontendIdentityPrincipalId
output apiIdentityId string = platform.outputs.apiIdentityId
output apiIdentityClientId string = platform.outputs.apiIdentityClientId
output apiIdentityPrincipalId string = platform.outputs.apiIdentityPrincipalId
output runtimeIdentityId string = platform.outputs.runtimeIdentityId
output runtimeIdentityClientId string = platform.outputs.runtimeIdentityClientId
output runtimeIdentityPrincipalId string = platform.outputs.runtimeIdentityPrincipalId
