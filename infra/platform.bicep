targetScope = 'resourceGroup'

param location string = resourceGroup().location
param environmentName string
param cosmosAccountName string
param storageAccountName string
param sharedAcrName string
param sharedAcrResourceGroup string
param azureOpenAiName string
param azureOpenAiResourceGroup string

var databaseName = 'csa-workbench-entra'
var containerName = 'appstate'
var frontendIdentityName = 'csa-workbench-frontend-identity'
var apiIdentityName = 'csa-workbench-api-identity'
var runtimeIdentityName = 'csa-workbench-runtime-identity'
var cosmosDataContributorRoleId = '00000000-0000-0000-0000-000000000002'
var blobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: null
      logAnalyticsConfiguration: null
    }
  }
}

resource frontendIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: frontendIdentityName
  location: location
}

resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: apiIdentityName
  location: location
}

resource runtimeIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: runtimeIdentityName
  location: location
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: cosmosAccountName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource cosmosDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmos
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
  }
}

resource cosmosContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosDatabase
  name: containerName
  properties: {
    resource: {
      id: containerName
      partitionKey: {
        paths: [
          '/sessionId'
        ]
        kind: 'Hash'
      }
    }
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    publicNetworkAccess: 'Enabled'
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource blobContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'engagement-artifacts'
  properties: {
    publicAccess: 'None'
  }
}

module acrRoles 'acr-roles.bicep' = {
  name: 'acr-roles'
  scope: resourceGroup(sharedAcrResourceGroup)
  params: {
    acrName: sharedAcrName
    frontendPrincipalId: frontendIdentity.properties.principalId
    apiPrincipalId: apiIdentity.properties.principalId
    runtimePrincipalId: runtimeIdentity.properties.principalId
  }
}

module openAiRole 'openai-role.bicep' = {
  name: 'openai-role'
  scope: resourceGroup(azureOpenAiResourceGroup)
  params: {
    accountName: azureOpenAiName
    runtimePrincipalId: runtimeIdentity.properties.principalId
  }
}

resource apiCosmosDataContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmos
  name: guid(cosmos.id, apiIdentityName, cosmosDataContributorRoleId)
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
    principalId: apiIdentity.properties.principalId
    scope: cosmos.id
  }
}

resource runtimeCosmosDataContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmos
  name: guid(cosmos.id, runtimeIdentityName, cosmosDataContributorRoleId)
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
    principalId: runtimeIdentity.properties.principalId
    scope: cosmos.id
  }
}

resource apiBlobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, apiIdentityName, blobDataContributorRoleId)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributorRoleId)
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

output environmentDefaultDomain string = environment.properties.defaultDomain
output environmentId string = environment.id
output cosmosAccountName string = cosmos.name
output cosmosEndpoint string = 'https://${cosmos.name}.documents.azure.com:443/'
output storageAccountName string = storage.name
output storageBlobEndpoint string = storage.properties.primaryEndpoints.blob
output frontendIdentityId string = frontendIdentity.id
output frontendIdentityClientId string = frontendIdentity.properties.clientId
output frontendIdentityPrincipalId string = frontendIdentity.properties.principalId
output apiIdentityId string = apiIdentity.id
output apiIdentityClientId string = apiIdentity.properties.clientId
output apiIdentityPrincipalId string = apiIdentity.properties.principalId
output runtimeIdentityId string = runtimeIdentity.id
output runtimeIdentityClientId string = runtimeIdentity.properties.clientId
output runtimeIdentityPrincipalId string = runtimeIdentity.properties.principalId
